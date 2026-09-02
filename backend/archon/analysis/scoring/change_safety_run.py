"""Change Safety stage runner (spec sections 31-32).

Sources signals from data Phases 2-5 already persisted:

    coverage     same TESTED_BY-edge proxy as Legacy Risk (0.5/0.0, always a proxy)
    complexity   Component.metrics["complexity"], same MODULE rollup as legacy_dna.py
    coupling     Component.metrics["architecture"]["fan_in"/"fan_out"]
    centrality   Component.metrics["architecture"]["betweenness_centrality"]
    callers-at-risk  Phase 2 CALLS edges into this component -> each caller's *this-run*
                 LegacyDNA.category / Hotspot.classification (a genuinely new
                 cross-engine signal - reads Phase 5's rows from the same run)
    assumptions  same rollup as Legacy Risk
    churn        Component.metrics["git"]["churn"]
    historical change-success rate / historical failures  omitted from the signal set,
                 omitted entirely - never defaulted

Cached per snapshot exactly like Legacy Risk: a later run over the same commit clones
the rows instead of recomputing. Safe because the caller-risk signal reads this-run's
LegacyDNA/Hotspot rows, which are themselves cloned identically when the snapshot is
unchanged (BUILDING_LEGACY_DNA/SCORING_HOTSPOTS clone first), so a cloned Change Safety
run reads self-consistent cloned data.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.analysis.scoring.change_safety import (
    CHANGE_SAFETY_VERSION,
    ChangeSafetySignals,
    change_safety_score,
)
from archon.analysis.scoring.thresholds import CHANGE_SAFETY_CONCERN_THRESHOLD
from archon.core.artifacts import write_json
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Assumption,
    ChangeAssessment,
    Component,
    Dependency,
    Evidence,
    Hotspot,
    LegacyDNA,
    RepositorySnapshot,
)
from archon.domain.enums import Classification, ComponentKind, DependencyKind, Stage

log = get_logger("archon.analysis.scoring.change_safety")

_ARTIFACT_KIND = "change_safety"
_SCOREABLE_KINDS = (
    ComponentKind.MODULE, ComponentKind.CLASS, ComponentKind.FUNCTION, ComponentKind.METHOD,
)
_AT_RISK_LEGACY = {"HIGH", "CRITICAL"}
_AT_RISK_HOTSPOT = {"RISKY", "CRITICAL"}
_MAX_DANGEROUS_EVIDENCE = 15


@dataclass
class ChangeSafetySummary:
    reused: bool
    scored: int
    by_category: dict[str, int]
    artifact_ref: str | None = None

    def as_dict(self) -> dict:
        return {
            "reused": self.reused, "scored": self.scored,
            "by_category": self.by_category, "artifact": self.artifact_ref,
        }


def _recommended_preparation(breakdown: dict, caller_count: int, at_risk_callers: int) -> list[str]:
    norm = breakdown["safe_normalized"]
    lines: list[str] = []
    if norm["coverage"] < CHANGE_SAFETY_CONCERN_THRESHOLD:
        lines.append("Add test coverage - no TESTED_BY edge found for this module.")
    if norm["complexity"] < CHANGE_SAFETY_CONCERN_THRESHOLD:
        lines.append("Complexity is high; consider decomposing before making changes.")
    if norm["coupling"] < CHANGE_SAFETY_CONCERN_THRESHOLD or norm["centrality"] < CHANGE_SAFETY_CONCERN_THRESHOLD:
        lines.append(
            "High coupling/centrality; changes here ripple widely - coordinate with "
            "owners of dependent modules."
        )
    if norm["caller_risk_ratio"] < CHANGE_SAFETY_CONCERN_THRESHOLD and caller_count:
        lines.append(
            f"{at_risk_callers} of {caller_count} caller(s) are themselves high-risk "
            "(Legacy DNA HIGH/CRITICAL or Hotspot RISKY/CRITICAL) - verify those call "
            "sites after any change."
        )
    if norm["assumption_count"] < CHANGE_SAFETY_CONCERN_THRESHOLD:
        lines.append("Hidden assumptions detected - review them before changing behaviour.")
    if norm["churn"] < CHANGE_SAFETY_CONCERN_THRESHOLD:
        lines.append("This component changes frequently; recent history may include unresolved risk.")
    return lines or ["No specific preparation flagged - proceed with standard review."]


def _write_artifact(session: Session, run: AnalysisRun, snapshot: RepositorySnapshot):
    rows = session.scalars(select(ChangeAssessment).where(ChangeAssessment.run_id == run.id)).all()
    return write_json(
        session, run.id, _ARTIFACT_KIND,
        {
            "schema": "archon.change_safety.v1",
            "snapshot_id": snapshot.id,
            "components": [
                {
                    "component_id": r.component_id, "safety_score": r.safety_score,
                    "risk_category": r.risk_category, "confidence": r.confidence,
                    "recommended_preparation": r.recommended_preparation,
                }
                for r in rows
            ],
        },
        stage=Stage.ASSESSING_CHANGE_SAFETY,
    )


def _prior_run_id(session: Session, run: AnalysisRun, snapshot_id: str) -> str | None:
    return session.scalar(
        select(ChangeAssessment.run_id)
        .where(ChangeAssessment.snapshot_id == snapshot_id, ChangeAssessment.run_id != run.id)
        .limit(1)
    )


def _clone_from_prior(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, prior_run_id: str
) -> ChangeSafetySummary:
    rows = session.scalars(
        select(ChangeAssessment).where(
            ChangeAssessment.snapshot_id == snapshot.id, ChangeAssessment.run_id == prior_run_id
        )
    ).all()
    by_category: dict[str, int] = {}
    for r in rows:
        by_category[r.risk_category] = by_category.get(r.risk_category, 0) + 1
        session.add(
            ChangeAssessment(
                run_id=run.id, snapshot_id=snapshot.id, component_id=r.component_id,
                engine_version=CHANGE_SAFETY_VERSION, safety_score=r.safety_score,
                risk_category=r.risk_category, factor_breakdown=r.factor_breakdown,
                recommended_preparation=r.recommended_preparation, confidence=r.confidence,
                evidence_ids=r.evidence_ids, produced_by=r.produced_by,
            )
        )
    session.flush()
    art = _write_artifact(session, run, snapshot)
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.ASSESSING_CHANGE_SAFETY, classification=Classification.FACT,
            summary=f"Reused cached change safety scoring for snapshot {snapshot.id} ({len(rows)} components)",
            produced_by=CHANGE_SAFETY_VERSION,
        )
    )
    session.flush()
    return ChangeSafetySummary(reused=True, scored=len(rows), by_category=by_category, artifact_ref=art.ref)


def run_change_safety(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
) -> ChangeSafetySummary:
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

    assumptions = session.scalars(select(Assumption).where(Assumption.run_id == run.id)).all()
    assumption_count_by_id = Counter(a.component_id for a in assumptions if a.component_id)
    assumption_count_by_path: dict[str, int] = {}
    for c in comps:
        n = assumption_count_by_id.get(c.id, 0)
        if n:
            assumption_count_by_path[c.path] = assumption_count_by_path.get(c.path, 0) + n

    # cross-engine: this run's already-persisted Legacy Risk / Hotspot rows
    legacy_category_by_id = {
        r.component_id: r.category
        for r in session.scalars(select(LegacyDNA).where(LegacyDNA.run_id == run.id)).all()
    }
    hotspot_class_by_id = {
        r.component_id: r.classification
        for r in session.scalars(select(Hotspot).where(Hotspot.run_id == run.id)).all()
    }

    def _is_at_risk(component_id: str) -> bool:
        cat = legacy_category_by_id.get(component_id)
        cls = hotspot_class_by_id.get(component_id)
        return (cat in _AT_RISK_LEGACY) or (cls in _AT_RISK_HOTSPOT)

    # CALLS edges grouped by dst -> distinct caller component ids
    call_edges = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == snapshot.id,
            Dependency.kind == DependencyKind.CALLS.value,
            Dependency.dst_component_id.is_not(None),
        )
    ).all()
    callers_by_dst: dict[str, set[str]] = {}
    for d in call_edges:
        callers_by_dst.setdefault(d.dst_component_id, set()).add(d.src_component_id)
    # module-level callers: union of callers into any component owned by that module
    owned_ids_by_path: dict[str, list[str]] = {}
    for c in comps:
        owned_ids_by_path.setdefault(c.path, []).append(c.id)
    callers_by_module_path: dict[str, set[str]] = {}
    for path, ids in owned_ids_by_path.items():
        union: set[str] = set()
        for cid in ids:
            union |= callers_by_dst.get(cid, set())
        callers_by_module_path[path] = union - set(ids)

    scored = 0
    by_category: dict[str, int] = {}

    for c in comps:
        if c.kind not in _SCOREABLE_KINDS or c.is_test:
            continue

        module = module_by_path.get(c.path)
        git = (c.metrics or {}).get("git") or {}

        if c.kind is ComponentKind.MODULE:
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
            centrality = arch.get("betweenness_centrality", 0.0)
            coupling_is_proxy = False
            has_tests = c.id in tested_module_ids
            callers = callers_by_module_path.get(c.path, set())
        elif module is not None:
            arch = (module.metrics or {}).get("architecture") or {}
            coupling = arch.get("fan_in", 0) + arch.get("fan_out", 0)
            centrality = arch.get("betweenness_centrality", 0.0)
            coupling_is_proxy = True
            has_tests = module.id in tested_module_ids
            callers = callers_by_dst.get(c.id, set())
        else:
            coupling = None
            centrality = None
            coupling_is_proxy = True
            has_tests = False
            callers = set()
        coverage = 0.5 if has_tests else 0.0

        caller_count = len(callers)
        at_risk_callers = sum(1 for cid in callers if _is_at_risk(cid))
        caller_risk_ratio = (at_risk_callers / caller_count) if caller_count else 0.0

        assumption_count = (
            assumption_count_by_path.get(c.path, 0)
            if c.kind is ComponentKind.MODULE
            else assumption_count_by_id.get(c.id, 0)
        )

        signals = ChangeSafetySignals(
            coverage=coverage, complexity=complexity, coupling=coupling,
            coupling_is_proxy=coupling_is_proxy, centrality=centrality,
            caller_risk_ratio=caller_risk_ratio, caller_count=caller_count,
            assumption_count=assumption_count, churn=git.get("churn"),
        )
        result = change_safety_score(signals)
        by_category[result.category] = by_category.get(result.category, 0) + 1
        scored += 1

        prep = _recommended_preparation(result.factor_breakdown, caller_count, at_risk_callers)

        session.add(
            ChangeAssessment(
                run_id=run.id, snapshot_id=snapshot.id, component_id=c.id,
                engine_version=CHANGE_SAFETY_VERSION, safety_score=result.score,
                risk_category=result.category, factor_breakdown=result.factor_breakdown,
                recommended_preparation=prep, confidence=result.confidence,
                evidence_ids=None, produced_by=CHANGE_SAFETY_VERSION,
            )
        )

    session.flush()
    art = _write_artifact(session, run, snapshot)
    _emit_evidence(session, run, scored, by_category)
    log.info(
        "change safety scored",
        extra={"extra_fields": {"run_id": run.id, "scored": scored, "by_category": by_category}},
    )
    return ChangeSafetySummary(reused=False, scored=scored, by_category=by_category, artifact_ref=art.ref)


def _emit_evidence(
    session: Session, run: AnalysisRun, scored: int, by_category: dict[str, int]
) -> None:
    cat_str = ", ".join(f"{k}={v}" for k, v in sorted(by_category.items()))
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.ASSESSING_CHANGE_SAFETY, classification=Classification.INFERENCE,
            summary=f"Change safety scored for {scored} component(s): {cat_str}",
            produced_by=CHANGE_SAFETY_VERSION, confidence=1.0, refs={"by_category": by_category},
        )
    )
    dangerous = session.scalars(
        select(ChangeAssessment).where(
            ChangeAssessment.run_id == run.id, ChangeAssessment.risk_category == "DANGEROUS"
        )
    ).all()
    for row in dangerous[:_MAX_DANGEROUS_EVIDENCE]:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.ASSESSING_CHANGE_SAFETY, classification=Classification.HYPOTHESIS,
                summary=f"Dangerous change safety (score={row.safety_score}) for component {row.component_id}",
                detail="; ".join(row.recommended_preparation),
                produced_by=CHANGE_SAFETY_VERSION, confidence=row.confidence,
            )
        )
    session.flush()
