"""Legacy Risk / Legacy DNA stage runner (spec sections 27, 30).

Sources the ``legacy_risk_score`` signals from data Phases 2-4 already persisted:

    complexity   Component.metrics["complexity"] (native at FUNCTION/METHOD/MODULE;
                 mean of children for CLASS)
    churn/age    Component.metrics["git"] (Phase 4 sets this on every component sharing
                 a file path, so it is native at every granularity)
    coupling     Component.metrics["architecture"]["fan_in"/"fan_out"] - native at
                 MODULE, borrowed from the owning module (flagged as a proxy) otherwise
    coverage     NOT YET REAL DATA (Phase 8). Proxy: 0.5 if the owning module has a
                 TESTED_BY edge, else 0.0. Always flagged ``coverage_is_proxy=True``.
    assumptions  count of Phase 4 ``assumptions`` rows for this run, rolled up to the
                 owning module by path
    debt_score   a *cheap subset* of the tech-debt detectors (long functions, large
                 classes, circular dependencies, high coupling) computed inline, because
                 the fixed Stage order runs BUILDING_LEGACY_DNA before ANALYZING_TECH_DEBT
                 - the full 13-detector set is only available to SCORING_HOTSPOTS later.
    failures     NOT YET AVAILABLE (Phase 9) - omitted entirely, never defaulted to zero.

Cached per snapshot: a later run over the same commit clones the rows instead of
recomputing (deterministic, no AI).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.analysis.scoring.legacy_risk import (
    LEGACY_RISK_VERSION,
    LegacyRiskSignals,
    legacy_risk_score,
)
from archon.analysis.scoring.tech_debt_detectors import (
    circular_dependencies,
    high_coupling,
    large_classes,
    long_functions,
)
from archon.analysis.scoring.thresholds import DEBT_SCORE_MAX, SEVERITY_WEIGHT
from archon.core.artifacts import write_json
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Assumption,
    Component,
    Dependency,
    Evidence,
    LegacyDNA,
    RepositorySnapshot,
    RiskAssessment,
)
from archon.domain.enums import Classification, ComponentKind, DependencyKind, Stage

log = get_logger("archon.analysis.scoring.legacy_dna")

_ARTIFACT_KIND = "legacy_dna"
_SCOREABLE_KINDS = (
    ComponentKind.MODULE, ComponentKind.CLASS, ComponentKind.FUNCTION, ComponentKind.METHOD,
)
_MAX_CRITICAL_EVIDENCE = 15


@dataclass
class LegacyDnaSummary:
    reused: bool
    scored: int
    by_category: dict[str, int]
    artifact_ref: str | None = None

    def as_dict(self) -> dict:
        return {
            "reused": self.reused, "scored": self.scored,
            "by_category": self.by_category, "artifact": self.artifact_ref,
        }


def _cheap_debt_by_component(
    components: list[Component], children_by_parent: dict[str, list[Component]]
) -> dict[str, float]:
    findings = [
        *long_functions(components),
        *large_classes(components, children_by_parent),
        *circular_dependencies(components),
        *high_coupling(components),
    ]
    raw: dict[str, float] = {}
    for f in findings:
        cid = f["component_id"]
        if not cid:
            continue
        raw[cid] = raw.get(cid, 0.0) + SEVERITY_WEIGHT[f["severity"]]
    return {cid: min(v / DEBT_SCORE_MAX, 1.0) for cid, v in raw.items()}


def _write_artifact(session: Session, run: AnalysisRun, snapshot: RepositorySnapshot):
    rows = session.scalars(select(LegacyDNA).where(LegacyDNA.run_id == run.id)).all()
    return write_json(
        session, run.id, _ARTIFACT_KIND,
        {
            "schema": "archon.legacy_dna.v1",
            "snapshot_id": snapshot.id,
            "components": [
                {
                    "component_id": r.component_id, "age_days": r.age_days,
                    "complexity": r.complexity, "churn": r.churn, "coupling": r.coupling,
                    "coverage": r.coverage, "coverage_is_proxy": r.coverage_is_proxy,
                    "assumption_count": r.assumption_count, "debt_score": r.debt_score,
                    "legacy_risk_score": r.legacy_risk_score, "category": r.category,
                    "confidence": r.confidence,
                }
                for r in rows
            ],
        },
        stage=Stage.BUILDING_LEGACY_DNA,
    )


def _prior_run_id(session: Session, run: AnalysisRun, snapshot_id: str) -> str | None:
    return session.scalar(
        select(LegacyDNA.run_id)
        .where(LegacyDNA.snapshot_id == snapshot_id, LegacyDNA.run_id != run.id)
        .limit(1)
    )


def _clone_from_prior(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, prior_run_id: str
) -> LegacyDnaSummary:
    rows = session.scalars(
        select(LegacyDNA).where(
            LegacyDNA.snapshot_id == snapshot.id, LegacyDNA.run_id == prior_run_id
        )
    ).all()
    by_category: dict[str, int] = {}
    for r in rows:
        by_category[r.category] = by_category.get(r.category, 0) + 1
        session.add(
            LegacyDNA(
                run_id=run.id, snapshot_id=snapshot.id, component_id=r.component_id,
                age_days=r.age_days, complexity=r.complexity, churn=r.churn,
                coupling=r.coupling, coverage=r.coverage, coverage_is_proxy=r.coverage_is_proxy,
                failure_count=r.failure_count, assumption_count=r.assumption_count,
                debt_score=r.debt_score, legacy_risk_score=r.legacy_risk_score,
                category=r.category, confidence=r.confidence,
                factor_breakdown=r.factor_breakdown, evidence_ids=r.evidence_ids,
                produced_by=r.produced_by,
            )
        )
        session.add(
            RiskAssessment(
                run_id=run.id, snapshot_id=snapshot.id, component_id=r.component_id,
                engine_version=LEGACY_RISK_VERSION, score=r.legacy_risk_score,
                category=r.category, factor_breakdown=r.factor_breakdown,
                confidence=r.confidence, evidence_ids=r.evidence_ids, produced_by=r.produced_by,
            )
        )
    session.flush()
    art = _write_artifact(session, run, snapshot)
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.BUILDING_LEGACY_DNA, classification=Classification.FACT,
            summary=f"Reused cached legacy risk scoring for snapshot {snapshot.id} ({len(rows)} components)",
            produced_by=LEGACY_RISK_VERSION,
        )
    )
    session.flush()
    return LegacyDnaSummary(reused=True, scored=len(rows), by_category=by_category, artifact_ref=art.ref)


def run_legacy_risk(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
) -> LegacyDnaSummary:
    prior = _prior_run_id(session, run, snapshot.id)
    if prior:
        return _clone_from_prior(session, run, snapshot, prior)

    comps = session.scalars(
        select(Component).where(Component.snapshot_id == snapshot.id)
    ).all()
    module_by_path = {c.path: c for c in comps if c.kind is ComponentKind.MODULE}
    children_by_parent: dict[str, list[Component]] = {}
    func_complexities_by_path: dict[str, list[float]] = {}
    for c in comps:
        if c.parent_id:
            children_by_parent.setdefault(c.parent_id, []).append(c)
        if c.kind in (ComponentKind.FUNCTION, ComponentKind.METHOD) and not c.is_test:
            cx = (c.metrics or {}).get("complexity")
            if cx is not None:
                func_complexities_by_path.setdefault(c.path, []).append(cx)

    tested_module_ids = set(
        session.scalars(
            select(Dependency.src_component_id).where(
                Dependency.snapshot_id == snapshot.id,
                Dependency.kind == DependencyKind.TESTED_BY.value,
            )
        ).all()
    )

    assumptions = session.scalars(
        select(Assumption).where(Assumption.run_id == run.id)
    ).all()
    assumption_count_by_id = Counter(a.component_id for a in assumptions if a.component_id)
    assumption_count_by_path: dict[str, int] = {}
    for c in comps:
        n = assumption_count_by_id.get(c.id, 0)
        if n:
            assumption_count_by_path[c.path] = assumption_count_by_path.get(c.path, 0) + n

    debt_by_component = _cheap_debt_by_component(comps, children_by_parent)

    scored = 0
    by_category: dict[str, int] = {}

    for c in comps:
        if c.kind not in _SCOREABLE_KINDS or c.is_test:
            continue

        module = module_by_path.get(c.path)
        git = (c.metrics or {}).get("git") or {}

        if c.kind is ComponentKind.MODULE:
            # Phase 2's own "complexity" on a MODULE row is top-level-body-only (excludes
            # every function it defines) - roll up the module's functions/methods instead,
            # since that is what actually reflects the module's risk.
            fn_cx = func_complexities_by_path.get(c.path)
            complexity = sum(fn_cx) / len(fn_cx) if fn_cx else (c.metrics or {}).get("complexity", 1.0)
        else:
            complexity = (c.metrics or {}).get("complexity")
            if complexity is None:
                kids = children_by_parent.get(c.id, [])
                kid_complexities = [
                    k.metrics.get("complexity") for k in kids
                    if (k.metrics or {}).get("complexity") is not None
                ]
                complexity = sum(kid_complexities) / len(kid_complexities) if kid_complexities else 1.0

        if c.kind is ComponentKind.MODULE:
            arch = (c.metrics or {}).get("architecture") or {}
            coupling = arch.get("fan_in", 0) + arch.get("fan_out", 0)
            coupling_is_proxy = False
            has_tests = c.id in tested_module_ids
        elif module is not None:
            arch = (module.metrics or {}).get("architecture") or {}
            coupling = arch.get("fan_in", 0) + arch.get("fan_out", 0)
            coupling_is_proxy = True
            has_tests = module.id in tested_module_ids
        else:
            coupling = None
            coupling_is_proxy = True
            has_tests = False
        coverage = 0.5 if has_tests else 0.0

        assumption_count = (
            assumption_count_by_path.get(c.path, 0)
            if c.kind is ComponentKind.MODULE
            else assumption_count_by_id.get(c.id, 0)
        )
        debt_score = debt_by_component.get(c.id, 0.0)

        signals = LegacyRiskSignals(
            complexity=complexity, churn=git.get("churn"), coverage=coverage,
            coupling=coupling, coupling_is_proxy=coupling_is_proxy,
            assumption_count=assumption_count, debt_score=debt_score,
            age_days=git.get("age_days"), age_is_defaulted=git.get("age_days") is None,
        )
        result = legacy_risk_score(signals)
        by_category[result.category] = by_category.get(result.category, 0) + 1
        scored += 1

        session.add(
            LegacyDNA(
                run_id=run.id, snapshot_id=snapshot.id, component_id=c.id,
                age_days=git.get("age_days"), complexity=complexity, churn=git.get("churn"),
                coupling=coupling, coverage=coverage, coverage_is_proxy=True,
                failure_count=None, assumption_count=assumption_count, debt_score=debt_score,
                legacy_risk_score=result.score, category=result.category,
                confidence=result.confidence, factor_breakdown=result.factor_breakdown,
                evidence_ids=None, produced_by=LEGACY_RISK_VERSION,
            )
        )
        session.add(
            RiskAssessment(
                run_id=run.id, snapshot_id=snapshot.id, component_id=c.id,
                engine_version=LEGACY_RISK_VERSION, score=result.score, category=result.category,
                factor_breakdown=result.factor_breakdown, confidence=result.confidence,
                evidence_ids=None, produced_by=LEGACY_RISK_VERSION,
            )
        )

    session.flush()
    art = _write_artifact(session, run, snapshot)
    _emit_evidence(session, run, snapshot, scored, by_category)
    log.info(
        "legacy risk scored",
        extra={"extra_fields": {"run_id": run.id, "scored": scored, "by_category": by_category}},
    )
    return LegacyDnaSummary(reused=False, scored=scored, by_category=by_category, artifact_ref=art.ref)


def _emit_evidence(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot,
    scored: int, by_category: dict[str, int],
) -> None:
    cat_str = ", ".join(f"{k}={v}" for k, v in sorted(by_category.items()))
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.BUILDING_LEGACY_DNA, classification=Classification.INFERENCE,
            summary=f"Legacy risk scored for {scored} component(s): {cat_str}",
            produced_by=LEGACY_RISK_VERSION, confidence=1.0, refs={"by_category": by_category},
        )
    )
    critical = session.scalars(
        select(LegacyDNA).where(LegacyDNA.run_id == run.id, LegacyDNA.category == "CRITICAL")
    ).all()
    for row in critical[:_MAX_CRITICAL_EVIDENCE]:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.BUILDING_LEGACY_DNA, classification=Classification.HYPOTHESIS,
                summary=f"Critical legacy risk (score={row.legacy_risk_score}) for component {row.component_id}",
                detail=f"complexity={row.complexity} churn={row.churn} debt_score={row.debt_score}",
                produced_by=LEGACY_RISK_VERSION, confidence=row.confidence,
            )
        )
    session.flush()
