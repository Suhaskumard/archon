"""Tech-debt detection stage runner (spec section 28).

Runs all 13 detectors from ``tech_debt_detectors`` - 6 pure lookups against Phase 2-4
data (incl. ``global_state`` reused verbatim from Phase 4's assumption heuristics) plus
one AST pass per source file for the remaining 7 - and persists one
``TechnicalDebtFinding`` row per hit. Cached per snapshot like the other Phase 5 engines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.analysis.scoring.tech_debt_detectors import (
    TECH_DEBT_VERSION,
    circular_dependencies,
    dead_code_candidates,
    detect_ast_debt,
    global_state_from_assumptions,
    high_coupling,
    large_classes,
    long_functions,
)
from archon.analysis.source.extractor import _module_qn_for
from archon.core.artifacts import write_json
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Assumption,
    Component,
    Dependency,
    Evidence,
    RepositorySnapshot,
    TechnicalDebtFinding,
)
from archon.domain.enums import Classification, ComponentKind, Stage

log = get_logger("archon.analysis.scoring.tech_debt")

_ARTIFACT_KIND = "tech_debt"
_MAX_FINDING_EVIDENCE = 25


@dataclass
class TechDebtSummary:
    reused: bool
    findings: int
    by_category: dict[str, int]
    artifact_ref: str | None = None

    def as_dict(self) -> dict:
        return {
            "reused": self.reused, "findings": self.findings,
            "by_category": self.by_category, "artifact": self.artifact_ref,
        }


def _module_qn_for_rel(rel: str) -> str:
    return _module_qn_for(rel)[0]


def _resolve_component(
    comps_by_path: dict[str, list[Component]], location: str
) -> str | None:
    if ":" not in location:
        return None
    path, _, line_str = location.rpartition(":")
    try:
        line = int(line_str)
    except ValueError:
        return None
    candidates = comps_by_path.get(path, [])
    best: Component | None = None
    best_span = None
    module_id = None
    for c in candidates:
        if c.kind is ComponentKind.MODULE:
            module_id = c.id
            continue
        if c.kind not in (ComponentKind.FUNCTION, ComponentKind.METHOD, ComponentKind.CLASS):
            continue
        start, end = c.start_line or 0, c.end_line or 10**9
        if start <= line <= end:
            span = end - start
            if best_span is None or span < best_span:
                best, best_span = c, span
    return best.id if best else module_id


def _prior_run_id(session: Session, run: AnalysisRun, snapshot_id: str) -> str | None:
    return session.scalar(
        select(TechnicalDebtFinding.run_id)
        .where(
            TechnicalDebtFinding.snapshot_id == snapshot_id,
            TechnicalDebtFinding.run_id != run.id,
        )
        .limit(1)
    )


def _write_artifact(session: Session, run: AnalysisRun, snapshot: RepositorySnapshot):
    rows = session.scalars(
        select(TechnicalDebtFinding).where(TechnicalDebtFinding.run_id == run.id)
    ).all()
    return write_json(
        session, run.id, _ARTIFACT_KIND,
        {
            "schema": "archon.tech_debt.v1",
            "snapshot_id": snapshot.id,
            "findings": [
                {
                    "category": r.category, "location": r.location, "evidence": r.evidence,
                    "severity": r.severity, "impact": r.impact, "confidence": r.confidence,
                    "recommendation": r.recommendation, "component_id": r.component_id,
                }
                for r in rows
            ],
        },
        stage=Stage.ANALYZING_TECH_DEBT,
    )


def _clone_from_prior(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, prior_run_id: str
) -> TechDebtSummary:
    rows = session.scalars(
        select(TechnicalDebtFinding).where(
            TechnicalDebtFinding.snapshot_id == snapshot.id,
            TechnicalDebtFinding.run_id == prior_run_id,
        )
    ).all()
    by_category: dict[str, int] = {}
    for r in rows:
        by_category[r.category] = by_category.get(r.category, 0) + 1
        session.add(
            TechnicalDebtFinding(
                run_id=run.id, snapshot_id=snapshot.id, component_id=r.component_id,
                category=r.category, location=r.location, evidence=r.evidence,
                severity=r.severity, impact=r.impact, confidence=r.confidence,
                recommendation=r.recommendation, produced_by=r.produced_by,
            )
        )
    session.flush()
    art = _write_artifact(session, run, snapshot)
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.ANALYZING_TECH_DEBT, classification=Classification.FACT,
            summary=f"Reused cached tech-debt findings for snapshot {snapshot.id} ({len(rows)} finding(s))",
            produced_by=TECH_DEBT_VERSION,
        )
    )
    session.flush()
    return TechDebtSummary(reused=True, findings=len(rows), by_category=by_category, artifact_ref=art.ref)


def run_tech_debt_detection(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, repo_dir: Path
) -> TechDebtSummary:
    prior = _prior_run_id(session, run, snapshot.id)
    if prior:
        return _clone_from_prior(session, run, snapshot, prior)

    comps = session.scalars(
        select(Component).where(Component.snapshot_id == snapshot.id)
    ).all()
    children_by_parent: dict[str, list[Component]] = {}
    comps_by_path: dict[str, list[Component]] = {}
    for c in comps:
        if c.parent_id:
            children_by_parent.setdefault(c.parent_id, []).append(c)
        comps_by_path.setdefault(c.path, []).append(c)

    deps = session.scalars(
        select(Dependency).where(Dependency.snapshot_id == snapshot.id)
    ).all()
    assumptions = session.scalars(
        select(Assumption).where(Assumption.run_id == run.id)
    ).all()

    findings = [
        *long_functions(comps),
        *large_classes(comps, children_by_parent),
        *circular_dependencies(comps),
        *high_coupling(comps),
        *dead_code_candidates(comps, deps),
        *global_state_from_assumptions(assumptions),
        *detect_ast_debt(repo_dir, _module_qn_for_rel),
    ]

    by_category: dict[str, int] = {}
    for f in findings:
        component_id = f["component_id"] or _resolve_component(comps_by_path, f["location"])
        by_category[f["category"]] = by_category.get(f["category"], 0) + 1
        session.add(
            TechnicalDebtFinding(
                run_id=run.id, snapshot_id=snapshot.id, component_id=component_id,
                category=f["category"], location=f["location"], evidence=f["evidence"],
                severity=f["severity"], impact=f["impact"], confidence=f["confidence"],
                recommendation=f["recommendation"], produced_by=TECH_DEBT_VERSION,
            )
        )
    session.flush()

    art = _write_artifact(session, run, snapshot)
    _emit_evidence(session, run, findings, by_category)
    log.info(
        "tech debt detected",
        extra={"extra_fields": {"run_id": run.id, "findings": len(findings), "by_category": by_category}},
    )
    return TechDebtSummary(
        reused=False, findings=len(findings), by_category=by_category, artifact_ref=art.ref,
    )


def _emit_evidence(
    session: Session, run: AnalysisRun, findings: list[dict], by_category: dict[str, int]
) -> None:
    cat_str = ", ".join(f"{k}={v}" for k, v in sorted(by_category.items()))
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.ANALYZING_TECH_DEBT, classification=Classification.FACT,
            summary=f"Detected {len(findings)} technical-debt finding(s): {cat_str}",
            produced_by=TECH_DEBT_VERSION, confidence=1.0, refs={"by_category": by_category},
        )
    )
    high_severity = [f for f in findings if f["severity"] in ("HIGH", "CRITICAL")]
    for f in high_severity[:_MAX_FINDING_EVIDENCE]:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.ANALYZING_TECH_DEBT, classification=Classification.FACT,
                summary=f"{f['category']} ({f['severity']}): {f['evidence']}",
                detail=f["location"], source_path=f["location"].split(":")[0] or None,
                produced_by=TECH_DEBT_VERSION, confidence=f["confidence"],
            )
        )
    session.flush()
