"""Archaeology stage runner (spec sections 24-26).

Deterministic behaviour facts + hidden-assumption detection, then the *first* AI step
(mock provider) interprets intent / behaviour / assumption risk. Cached per snapshot:
a later run over the same commit copies the rows instead of recomputing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.analysis.archaeology.assumptions import detect_assumptions
from archon.analysis.archaeology.behavior import BEHAVIOR_VERSION, reconstruct_behavior
from archon.analysis.source.extractor import _module_qn_for
from archon.config import get_settings
from archon.core.artifacts import write_json
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Assumption,
    BehaviorReconstruction,
    Commit,
    Component,
    Evidence,
    RepositorySnapshot,
)
from archon.domain.ai_schemas import AssumptionAnalysis, BehaviorAnalysis, HistoricalIntent
from archon.domain.enums import Classification, ComponentKind, Stage
from archon.providers.ai import get_ai_provider

log = get_logger("archon.analysis.archaeology")

ARCHAEOLOGY_VERSION = "archaeology.v1"
ASSUMPTIONS_VERSION = "assumptions.v1"
_MAX_HIGH_RISK_EVIDENCE = 15
_ARTIFACT_KIND = "archaeology"


@dataclass
class ArchaeologySummary:
    reused: bool
    behaviors: int
    assumptions: int
    high_risk: int
    by_kind: dict[str, int] = field(default_factory=dict)
    artifact_ref: str | None = None

    def as_dict(self) -> dict:
        return {
            "reused": self.reused,
            "behaviors": self.behaviors,
            "assumptions": self.assumptions,
            "high_risk": self.high_risk,
            "by_kind": self.by_kind,
            "artifact": self.artifact_ref,
        }


# --- helpers -----------------------------------------------------------------------


def _module_qn_for_rel(rel: str) -> str:
    return _module_qn_for(rel)[0]


def _known_refs(session: Session, snapshot_id: str) -> dict[str, set[str]]:
    qns: set[str] = set()
    files: set[str] = set()
    for qn, path in session.execute(
        select(Component.qualified_name, Component.path).where(
            Component.snapshot_id == snapshot_id
        )
    ).all():
        qns.add(qn)
        files.add(path)
    shas = set(
        session.scalars(select(Commit.sha).where(Commit.snapshot_id == snapshot_id)).all()
    )
    return {"component": qns, "file": files, "commit": shas, "test": qns}


def _component_git(component: Component) -> dict:
    return (component.metrics or {}).get("git", {}) or {}


def _write_artifact(session: Session, run: AnalysisRun, snapshot: RepositorySnapshot):
    behaviors = session.scalars(
        select(BehaviorReconstruction).where(BehaviorReconstruction.run_id == run.id)
    ).all()
    assumptions = session.scalars(
        select(Assumption).where(Assumption.run_id == run.id)
    ).all()
    return write_json(
        session, run.id, _ARTIFACT_KIND,
        {
            "schema": "archon.archaeology.v1",
            "snapshot_id": snapshot.id,
            "behaviors": [
                {
                    "component_id": b.component_id,
                    "purpose": b.purpose,
                    "historical_context": b.historical_context,
                    "current_role": b.current_role,
                    "inputs": b.inputs,
                    "outputs": b.outputs,
                    "side_effects": b.side_effects,
                    "exceptions": b.exceptions,
                    "callers": b.callers,
                    "callees": b.callees,
                    "tests": b.tests,
                    "likely_invariants": b.likely_invariants,
                    "git": b.git,
                    "classification": b.classification,
                    "confidence": b.confidence,
                }
                for b in behaviors
            ],
            "assumptions": [
                {
                    "kind": a.kind, "description": a.description, "location": a.location,
                    "risk": a.risk, "confidence": a.confidence,
                    "suggested_test": a.suggested_test, "component_id": a.component_id,
                }
                for a in assumptions
            ],
        },
        stage=Stage.ARCHAEOLOGIZING,
    )


# --- caching -----------------------------------------------------------------------


def _prior_run_id(session: Session, run: AnalysisRun, snapshot_id: str) -> str | None:
    return session.scalar(
        select(BehaviorReconstruction.run_id)
        .where(
            BehaviorReconstruction.snapshot_id == snapshot_id,
            BehaviorReconstruction.run_id != run.id,
        )
        .limit(1)
    )


def _clone_from_prior(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, prior_run_id: str
) -> ArchaeologySummary:
    behaviors = session.scalars(
        select(BehaviorReconstruction).where(
            BehaviorReconstruction.snapshot_id == snapshot.id,
            BehaviorReconstruction.run_id == prior_run_id,
        )
    ).all()
    assumptions = session.scalars(
        select(Assumption).where(
            Assumption.snapshot_id == snapshot.id, Assumption.run_id == prior_run_id
        )
    ).all()
    for b in behaviors:
        session.add(
            BehaviorReconstruction(
                run_id=run.id, snapshot_id=snapshot.id, component_id=b.component_id,
                purpose=b.purpose, historical_context=b.historical_context,
                current_role=b.current_role, inputs=b.inputs, outputs=b.outputs,
                side_effects=b.side_effects, exceptions=b.exceptions, callers=b.callers,
                callees=b.callees, tests=b.tests, likely_invariants=b.likely_invariants,
                git=b.git, classification=b.classification, confidence=b.confidence,
                produced_by=b.produced_by,
            )
        )
    by_kind: dict[str, int] = {}
    high = 0
    for a in assumptions:
        by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
        high += 1 if a.risk == "HIGH" else 0
        session.add(
            Assumption(
                run_id=run.id, snapshot_id=snapshot.id, component_id=a.component_id,
                kind=a.kind, description=a.description, location=a.location, detail=a.detail,
                risk=a.risk, confidence=a.confidence, suggested_test=a.suggested_test,
                produced_by=a.produced_by, evidence_ids=a.evidence_ids,
            )
        )
    session.flush()
    art = _write_artifact(session, run, snapshot)
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.ARCHAEOLOGIZING, classification=Classification.FACT,
            summary=f"Reused cached archaeology for snapshot {snapshot.id} "
                    f"({len(behaviors)} behaviours, {len(assumptions)} assumptions)",
            produced_by=ARCHAEOLOGY_VERSION,
        )
    )
    session.flush()
    return ArchaeologySummary(
        reused=True, behaviors=len(behaviors), assumptions=len(assumptions),
        high_risk=high, by_kind=by_kind, artifact_ref=art.ref,
    )


# --- main --------------------------------------------------------------------------


def run_archaeology(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, repo_dir
) -> ArchaeologySummary:
    prior = _prior_run_id(session, run, snapshot.id)
    if prior:
        return _clone_from_prior(session, run, snapshot, prior)

    provider = get_ai_provider()
    known = _known_refs(session, snapshot.id)
    settings = get_settings()

    comps = session.scalars(
        select(Component).where(Component.snapshot_id == snapshot.id)
    ).all()
    by_qn = {c.qualified_name: c for c in comps}
    by_path_module = {
        c.path: c for c in comps if c.kind is ComponentKind.MODULE
    }

    # --- assumptions ------------------------------------------------------
    raw = detect_assumptions(repo_dir, _module_qn_for_rel)
    by_kind: dict[str, int] = {}
    high_risk_rows: list[Assumption] = []
    for ra in raw:
        comp = by_qn.get(ra.function_qn) or by_path_module.get(ra.path)
        cmeta = {
            "qualified_name": (comp.qualified_name if comp else ra.function_qn),
            "path": ra.path,
            "git": _component_git(comp) if comp else {},
        }
        beh_tests = _tests_for(session, snapshot.id, comp) if comp else []
        analysis = provider.complete_structured(
            "assumption_analysis",
            AssumptionAnalysis,
            {
                "assumption": {"kind": ra.kind, "description": ra.description,
                               "location": f"{ra.path}:{ra.line}"},
                "component": cmeta,
                "tests": beh_tests,
                "known_refs": known,
            },
        )
        row = Assumption(
            run_id=run.id, snapshot_id=snapshot.id,
            component_id=comp.id if comp else None,
            kind=analysis.kind, description=analysis.description,
            location=f"{ra.path}:{ra.line}", detail=ra.evidence,
            risk=analysis.risk, confidence=analysis.confidence.value,
            suggested_test=analysis.suggested_test, produced_by=ASSUMPTIONS_VERSION,
            evidence_ids=[e.model_dump() for e in analysis.evidence],
        )
        session.add(row)
        by_kind[analysis.kind] = by_kind.get(analysis.kind, 0) + 1
        if analysis.risk == "HIGH":
            high_risk_rows.append(row)
    session.flush()

    assumptions_by_fn: dict[str, list] = {}
    for ra in raw:
        assumptions_by_fn.setdefault(ra.function_qn, []).append(ra)

    # --- behaviour ------------------------------------------------------
    targets = _select_targets(comps, settings.ai_max_components_per_run)
    for comp in targets:
        facts = reconstruct_behavior(
            session, snapshot.id, comp, assumptions_by_fn=assumptions_by_fn
        )
        ctx = {
            "component": {
                "qualified_name": comp.qualified_name, "kind": comp.kind.value,
                "name": comp.name, "path": comp.path, "role": comp.role,
                "docstring": facts.docstring, "git": facts.git,
            },
            "callers": facts.callers, "callees": facts.callees, "tests": facts.tests,
            "inputs": facts.inputs, "outputs": facts.outputs,
            "side_effects": facts.side_effects, "likely_invariants": facts.likely_invariants,
            "commit_refs": _recent_shas(session, snapshot.id, comp),
            "known_refs": known,
        }
        intent = provider.complete_structured("historical_intent", HistoricalIntent, ctx)
        behaviour = provider.complete_structured("behavior_analysis", BehaviorAnalysis, ctx)
        session.add(
            BehaviorReconstruction(
                run_id=run.id, snapshot_id=snapshot.id, component_id=comp.id,
                purpose=intent.likely_purpose,
                historical_context=intent.historical_context,
                current_role=intent.current_role,
                inputs=behaviour.inputs or facts.inputs,
                outputs=behaviour.outputs or facts.outputs,
                side_effects=behaviour.side_effects or facts.side_effects,
                exceptions=facts.exceptions,
                callers=facts.callers, callees=facts.callees, tests=facts.tests,
                likely_invariants=behaviour.likely_invariants or facts.likely_invariants,
                git=facts.git,
                classification=intent.classification.value,
                confidence=intent.confidence.value,
                produced_by=f"{BEHAVIOR_VERSION}+{ARCHAEOLOGY_VERSION}",
            )
        )
    session.flush()

    n_behaviors = len(targets)
    n_assumptions = len(raw)
    _emit_evidence(session, run, n_behaviors, n_assumptions, by_kind, high_risk_rows)
    art = _write_artifact(session, run, snapshot)
    log.info(
        "archaeology complete",
        extra={"extra_fields": {"run_id": run.id, "behaviors": n_behaviors,
                                "assumptions": n_assumptions, "by_kind": by_kind}},
    )
    return ArchaeologySummary(
        reused=False, behaviors=n_behaviors, assumptions=n_assumptions,
        high_risk=len(high_risk_rows), by_kind=by_kind, artifact_ref=art.ref,
    )


# --- support -----------------------------------------------------------------------


def _select_targets(comps: list[Component], cap: int) -> list[Component]:
    modules = [c for c in comps if c.kind is ComponentKind.MODULE]
    funcs = [c for c in comps if c.kind in (ComponentKind.FUNCTION, ComponentKind.METHOD)]

    def score(c: Component) -> float:
        m = c.metrics or {}
        churn = (m.get("git", {}) or {}).get("churn", 0) or 0
        return (churn + 1) * (m.get("complexity", 1) or 1)

    funcs.sort(key=score, reverse=True)
    room = max(cap - len(modules), 0)
    return modules + funcs[:room]


def _tests_for(session: Session, snapshot_id: str, comp: Component) -> list[str]:
    from archon.db.models import Dependency
    from archon.domain.enums import DependencyKind

    module = comp
    if comp.kind not in (ComponentKind.MODULE, ComponentKind.FILE):
        module = session.scalar(
            select(Component).where(
                Component.snapshot_id == snapshot_id,
                Component.kind == ComponentKind.MODULE,
                Component.path == comp.path,
            )
        ) or comp
    rows = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == snapshot_id,
            Dependency.src_component_id == module.id,
            Dependency.kind == DependencyKind.TESTED_BY.value,
        )
    ).all()
    return sorted({r.target_name for r in rows})


def _recent_shas(session: Session, snapshot_id: str, comp: Component) -> list[str]:
    from archon.db.models import Dependency
    from archon.domain.enums import DependencyKind

    rows = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == snapshot_id,
            Dependency.src_component_id == comp.id,
            Dependency.kind == DependencyKind.CHANGED_BY.value,
        )
    ).all()
    return [r.target_name for r in rows][:3]


def _emit_evidence(
    session: Session,
    run: AnalysisRun,
    behaviors: int,
    assumptions: int,
    by_kind: dict[str, int],
    high_risk_rows: list[Assumption],
) -> None:
    kinds = ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.ARCHAEOLOGIZING, classification=Classification.FACT,
            summary=(
                f"Reconstructed behaviour for {behaviors} component(s); "
                f"{assumptions} hidden assumption(s) ({len(high_risk_rows)} high-risk)"
            ),
            detail=kinds, produced_by=ARCHAEOLOGY_VERSION, confidence=1.0,
            refs={"by_kind": by_kind},
        )
    )
    for row in high_risk_rows[:_MAX_HIGH_RISK_EVIDENCE]:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.ARCHAEOLOGIZING,
                classification=Classification.HYPOTHESIS,
                summary=f"High-risk {row.kind} assumption: {row.description}",
                detail=f"{row.location} - {row.suggested_test}",
                source_path=(row.location or "").split(":")[0] or None,
                produced_by=ASSUMPTIONS_VERSION, confidence=0.6,
            )
        )
    session.flush()
