"""Deterministic modernization planning (spec section 46).

``generate_modernization_plan`` is the ``MODERNIZING`` stage body:

1. ``assemble_targets``      - deterministic: every module with a modernization-worthy
                               signal (legacy risk >= MODERATE, any tech-debt finding,
                               a WATCH+ hotspot, or an import cycle), with its rolled-up
                               signals.
2. AI ``modernization_recommendation`` - picks strategy/risk/effort/impact/rationale
                               per target (mock; degrade-and-continue on AI error).
3. ``compute_safe_order``    - deterministic, versioned: topological order over the
                               condensed module import graph (dependencies first),
                               then ``add_tests`` before structural strategies, then
                               safer-first by change safety.

The safe *ordering* is never the AI's job (spec: "sequencing derived from the
dependency + change-safety graph").
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

import networkx as nx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archon.analysis.graph.builder import build_module_graph
from archon.analysis.graph.derive import find_cycles
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    ChangeAssessment,
    Component,
    Evidence,
    Hotspot,
    LegacyDNA,
    ModernizationRecommendation,
    RepositorySnapshot,
    TechnicalDebtFinding,
)
from archon.domain import ai_schemas
from archon.domain.ai_schemas import MODERNIZATION_SCHEMA_VERSION
from archon.domain.enums import Classification, ComponentKind, ModernizationStrategy, Stage
from archon.providers.ai import get_ai_provider
from archon.providers.ai.base import AIOutputError, AIProviderError

log = get_logger("archon.modernization")

MODERNIZATION_VERSION = "modernization.v1"

_RISK_ORDER = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
_HOTSPOT_ORDER = ["STABLE", "WATCH", "RISKY", "CRITICAL"]

_STRATEGY_ENUM = {
    "add_tests": ModernizationStrategy.ADD_TESTS,
    "extract_dependency": ModernizationStrategy.EXTRACT_DEPENDENCY,
    "refactor": ModernizationStrategy.REFACTOR,
    "replace_dependency": ModernizationStrategy.REPLACE_DEPENDENCY,
    "rewrite": ModernizationStrategy.REWRITE,
}
# lower = do first
_STRATEGY_RANK = {
    ModernizationStrategy.ADD_TESTS: 0,
    ModernizationStrategy.EXTRACT_DEPENDENCY: 1,
    ModernizationStrategy.REPLACE_DEPENDENCY: 1,
    ModernizationStrategy.REFACTOR: 2,
    ModernizationStrategy.REWRITE: 3,
}


@dataclass
class ModernizationSummary:
    recommended: int
    targets: int
    strategies: dict[str, int]

    def as_dict(self) -> dict:
        return {
            "recommended": self.recommended,
            "targets": self.targets,
            "strategies": self.strategies,
        }


def _cat(value: object) -> str:
    return (value.value if hasattr(value, "value") else str(value)).upper() if value is not None else ""


def assemble_targets(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
) -> list[dict]:
    comps = list(
        session.scalars(select(Component).where(Component.snapshot_id == snapshot.id)).all()
    )
    qn_of = {c.id: c.qualified_name for c in comps}
    module_by_path = {c.path: c for c in comps if c.kind is ComponentKind.MODULE}
    module_qn_of_path = {p: c.qualified_name for p, c in module_by_path.items()}

    legacy = {
        qn_of[r.component_id]: r
        for r in session.scalars(select(LegacyDNA).where(LegacyDNA.run_id == run.id)).all()
        if r.component_id in qn_of
    }
    hotspots = {
        qn_of[r.component_id]: r
        for r in session.scalars(select(Hotspot).where(Hotspot.run_id == run.id)).all()
        if r.component_id in qn_of
    }
    change = {
        qn_of[r.component_id]: r
        for r in session.scalars(
            select(ChangeAssessment).where(ChangeAssessment.run_id == run.id)
        ).all()
        if r.component_id in qn_of
    }

    debt_by_module: dict[str, set[str]] = defaultdict(set)
    for f in session.scalars(
        select(TechnicalDebtFinding).where(TechnicalDebtFinding.run_id == run.id)
    ).all():
        # tech-debt findings hang off file/function/class components; roll them up to
        # the owning module via shared path.
        owner_qn = None
        if f.component_id and f.component_id in qn_of:
            comp = next((c for c in comps if c.id == f.component_id), None)
            owner_qn = module_qn_of_path.get(comp.path) if comp else None
        if owner_qn is None and f.location:
            owner_qn = module_qn_of_path.get(f.location.split(":")[0])
        if owner_qn:
            debt_by_module[owner_qn].add(_cat(f.category))

    mg = build_module_graph(session, snapshot.id)
    cycle_qns = {qn for cyc in find_cycles(mg) for qn in cyc}

    targets: list[dict] = []
    for c in comps:
        if c.kind is not ComponentKind.MODULE or c.is_test:
            continue
        qn = c.qualified_name
        dna = legacy.get(qn)
        hot = hotspots.get(qn)
        ca = change.get(qn)
        debt = debt_by_module.get(qn, set())
        cat = _cat(dna.category) if dna else ""
        hot_cls = _cat(hot.classification) if hot else ""
        coverage = dna.coverage if dna else None

        worthy = (
            (cat in _RISK_ORDER and _RISK_ORDER.index(cat) >= _RISK_ORDER.index("MODERATE"))
            or bool(debt)
            or (hot_cls in _HOTSPOT_ORDER and _HOTSPOT_ORDER.index(hot_cls) >= _HOTSPOT_ORDER.index("WATCH"))
            or qn in cycle_qns
        )
        if not worthy:
            continue

        targets.append({
            "qualified_name": qn,
            "legacy_risk_score": round(dna.legacy_risk_score, 4) if dna else 0.0,
            "legacy_category": cat or "LOW",
            "coverage": coverage,
            "complexity": (dna.complexity if dna else None) or (c.metrics or {}).get("complexity"),
            "coupling": dna.coupling if dna else None,
            "change_safety_score": round(ca.safety_score, 4) if ca else None,
            "change_safety_category": _cat(ca.risk_category) if ca else None,
            "change_assessment_id": ca.id if ca else None,
            "in_cycle": qn in cycle_qns,
            "hotspot": hot_cls or None,
            "debt_categories": sorted(debt),
            "recommended_preparation": list(ca.recommended_preparation or []) if ca else [],
            "component_id": c.id,
        })
    targets.sort(key=lambda t: (-t["legacy_risk_score"], t["qualified_name"]))
    return targets


def compute_safe_order(
    session: Session, snapshot: RepositorySnapshot, items: list, targets: list[dict]
) -> list[dict]:
    """Return one ``{item, order_index, breakdown, dependencies}`` per item, safest-first."""
    mg = build_module_graph(session, snapshot.id)
    qn_by_module = {data["qualified_name"]: n for n, data in mg.nodes(data=True)}
    module_by_qn = {v: k for k, v in qn_by_module.items()}

    # condense SCCs so import cycles don't break the topological sort, then order
    # dependencies before dependents.
    generation: dict[str, int] = {}
    if mg.number_of_nodes():
        cond = nx.condensation(mg)
        order = list(nx.topological_sort(cond))[::-1]  # dependencies first
        scc_rank = {scc: i for i, scc in enumerate(order)}
        mapping = cond.graph["mapping"]
        for module_id, qn in module_by_qn.items():
            generation[qn] = scc_rank[mapping[module_id]]
    last_gen = (max(generation.values()) + 1) if generation else 0

    cs_by_qn = {t["qualified_name"]: t.get("change_safety_score") for t in targets}
    risk_by_qn = {t["qualified_name"]: t.get("legacy_risk_score", 0.0) for t in targets}
    target_qns = {t["qualified_name"] for t in targets}

    def sort_key(item):
        strat = _STRATEGY_ENUM.get(item.strategy, ModernizationStrategy.REFACTOR)
        cs = cs_by_qn.get(item.target)
        return (
            generation.get(item.target, last_gen),
            _STRATEGY_RANK[strat],
            -(cs if cs is not None else 0.0),
            risk_by_qn.get(item.target, 0.0),
            item.target,
            item.strategy,
        )

    ordered_items = sorted(items, key=sort_key)

    out: list[dict] = []
    for idx, item in enumerate(ordered_items):
        strat = _STRATEGY_ENUM.get(item.strategy, ModernizationStrategy.REFACTOR)
        module_id = qn_by_module.get(item.target)
        deps = sorted(
            module_by_qn[s]
            for s in (mg.successors(module_id) if module_id is not None else [])
            if module_by_qn.get(s) in target_qns and module_by_qn[s] != item.target
        )
        out.append({
            "item": item,
            "strategy_enum": strat,
            "order_index": idx,
            "dependencies": deps,
            "breakdown": {
                "topo_generation": generation.get(item.target, last_gen),
                "strategy_rank": _STRATEGY_RANK[strat],
                "change_safety_score": cs_by_qn.get(item.target),
                "legacy_risk_score": risk_by_qn.get(item.target, 0.0),
            },
        })
    return out


def _fact(session: Session, run_id: str, summary: str, detail: str | None = None) -> None:
    session.add(
        Evidence(
            run_id=run_id, stage=Stage.MODERNIZING, classification=Classification.FACT,
            summary=summary[:512], detail=detail,
            produced_by=MODERNIZATION_VERSION, confidence=1.0,
        )
    )
    session.flush()


def generate_modernization_plan(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
) -> ModernizationSummary:
    session.execute(
        delete(ModernizationRecommendation).where(ModernizationRecommendation.run_id == run.id)
    )
    session.flush()

    targets = assemble_targets(session, run, snapshot)
    if not targets:
        _fact(session, run.id, "No modernization targets - repository is in good shape")
        log.info("modernization: no targets", extra={"extra_fields": {"run_id": run.id}})
        return ModernizationSummary(recommended=0, targets=0, strategies={})

    ctx = {
        "targets": [
            {k: v for k, v in t.items() if k != "component_id"} for t in targets
        ],
        "known_refs": {"component": {t["qualified_name"] for t in targets}},
    }
    ai = get_ai_provider()
    try:
        result = ai.complete_structured(
            "modernization_recommendation", ai_schemas.ModernizationRecommendation, ctx
        )
    except (AIProviderError, AIOutputError) as exc:
        # analysis stage - degrade and continue, never fail the run (spec section 10)
        _fact(
            session, run.id,
            "Modernization AI op failed - no recommendations produced",
            detail=str(exc),
        )
        log.warning("modernization ai op failed", extra={"extra_fields": {"run_id": run.id}})
        return ModernizationSummary(recommended=0, targets=len(targets), strategies={})

    items = list(result.recommendations)
    if not items:
        _fact(session, run.id, "AI produced no modernization recommendations for the targets")
        return ModernizationSummary(recommended=0, targets=len(targets), strategies={})

    ordered = compute_safe_order(session, snapshot, items, targets)

    component_id_by_qn = {t["qualified_name"]: t["component_id"] for t in targets}
    change_ref_by_qn = {t["qualified_name"]: t.get("change_assessment_id") for t in targets}
    confidence = result.confidence.score
    classification = result.classification.value if hasattr(result.classification, "value") else str(result.classification)
    strategies: Counter = Counter()

    for entry in ordered:
        item = entry["item"]
        strat: ModernizationStrategy = entry["strategy_enum"]
        rec = ModernizationRecommendation(
            run_id=run.id, snapshot_id=snapshot.id,
            component_id=component_id_by_qn.get(item.target),
            target=item.target, strategy=strat,
            risk=item.risk, effort=item.effort, impact=item.impact,
            change_safety_ref=change_ref_by_qn.get(item.target),
            dependencies=entry["dependencies"],
            required_tests=list(item.required_tests),
            prerequisites=list(item.prerequisites),
            order_index=entry["order_index"],
            rationale=item.rationale,
            confidence=confidence, classification=classification,
            ai_schema_version=MODERNIZATION_SCHEMA_VERSION,
            produced_by=MODERNIZATION_VERSION,
        )
        session.add(rec)
        session.flush()
        strategies[strat.value] += 1

        ev = Evidence(
            run_id=run.id, stage=Stage.MODERNIZING,
            classification=Classification.RECOMMENDATION, confidence=confidence,
            summary=f"[{entry['order_index']}] {strat.value} {item.target}"[:512],
            detail=item.rationale,
            produced_by=MODERNIZATION_VERSION,
            refs={
                "recommendation_id": rec.id, "target": item.target,
                "strategy": strat.value, "order_index": entry["order_index"],
            },
        )
        session.add(ev)
        session.flush()
        rec.evidence_ids = [ev.id]
        session.flush()

    log.info(
        "modernization plan built",
        extra={"extra_fields": {
            "run_id": run.id, "recommended": len(ordered), "targets": len(targets),
        }},
    )
    return ModernizationSummary(
        recommended=len(ordered), targets=len(targets), strategies=dict(strategies)
    )
