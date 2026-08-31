"""Change Impact analysis (spec sections 31-32).

For a target component, resolve its owning MODULE and report: direct + indirect
dependents (module dependency graph traversal), callers (Phase 2 CALLS edges), related
tests (Phase 3 TESTED_BY edges), historical co-changes (Phase 4 CHANGED_WITH edges),
external integrations (Phase 2's unresolved external Dependency rows), and a
deterministic "what could break / which tests to run / what to do first" narrative.
No AI - purely a traversal + template, like every Phase 5-6 engine.

Precomputed for every MODULE component by the ``ANALYZING_CHANGE_IMPACT`` stage;
``POST /runs/{id}/change-impact`` upserts a fresh row on demand for any other component
not already covered.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.analysis.graph.builder import build_module_graph
from archon.core.artifacts import write_json
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    ChangeImpact,
    Component,
    Dependency,
    Evidence,
    RepositorySnapshot,
)
from archon.domain.enums import Classification, ComponentKind, DependencyKind, Stage

log = get_logger("archon.analysis.scoring.change_impact")

CHANGE_IMPACT_VERSION = "change_impact.v1"
_ARTIFACT_KIND = "change_impact"
_MAX_WHAT_COULD_BREAK = 10


@dataclass
class ChangeImpactSummary:
    computed: int
    reused: int

    def as_dict(self) -> dict:
        return {"computed": self.computed, "reused": self.reused}


def direct_and_indirect_dependents(mg: nx.DiGraph, node: str) -> tuple[set[str], set[str]]:
    """Edges in ``mg`` point dependent -> dependency, so a node's *dependents* are its
    predecessors (direct) and its ancestors (direct + transitive)."""
    if node not in mg:
        return set(), set()
    direct = set(mg.predecessors(node))
    indirect = nx.ancestors(mg, node) - direct - {node}
    return direct, indirect


def _entry(comp: Component) -> dict:
    return {"component_id": comp.id, "qualified_name": comp.qualified_name, "kind": comp.kind.value}


def _module_for(module_by_path: dict[str, Component], comp: Component) -> Component | None:
    if comp.kind is ComponentKind.MODULE:
        return comp
    return module_by_path.get(comp.path)


def _potential_impact(
    direct_entries: list[dict], test_entries: list[dict], caller_entries: list[dict]
) -> dict:
    what_could_break = [
        f"`{e['qualified_name']}` directly depends on this module and may break if its "
        "interface changes"
        for e in direct_entries[:_MAX_WHAT_COULD_BREAK]
    ]
    if len(direct_entries) > _MAX_WHAT_COULD_BREAK:
        what_could_break.append(
            f"...and {len(direct_entries) - _MAX_WHAT_COULD_BREAK} more direct dependent(s)"
        )

    if test_entries:
        tests_to_run = [f"Run tests in `{e['qualified_name']}`" for e in test_entries]
    else:
        tests_to_run = [
            "No TESTED_BY edges found for this component - no automated tests are known "
            "to cover it; manual verification required."
        ]

    what_to_do_first: list[str] = []
    if caller_entries:
        names = ", ".join(e["qualified_name"] for e in caller_entries[:5])
        what_to_do_first.append(f"Review the {len(caller_entries)} direct caller(s): {names}")
    if test_entries:
        what_to_do_first.append(f"Re-run the {len(test_entries)} test(s) covering this component")
    if not caller_entries and not test_entries:
        what_to_do_first.append(
            "No callers or test coverage found - manually verify behaviour before and "
            "after the change."
        )

    return {
        "what_could_break": what_could_break,
        "tests_to_run": tests_to_run,
        "what_to_do_first": what_to_do_first,
    }


def _compute(
    session: Session,
    snapshot: RepositorySnapshot,
    target: Component,
    mg: nx.DiGraph,
    comps_by_path: dict[str, list[Component]],
    module_by_path: dict[str, Component],
) -> dict:
    module = _module_for(module_by_path, target) or target
    owned_ids = [c.id for c in comps_by_path.get(module.path, [])]

    direct_ids, indirect_ids = direct_and_indirect_dependents(mg, module.id)
    id_to_comp = {c.id: c for group in comps_by_path.values() for c in group}
    direct_entries = [_entry(id_to_comp[i]) for i in direct_ids if i in id_to_comp]
    indirect_entries = [_entry(id_to_comp[i]) for i in indirect_ids if i in id_to_comp]

    callers = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == snapshot.id,
            Dependency.kind == DependencyKind.CALLS.value,
            Dependency.dst_component_id.in_(owned_ids),
        )
    ).all()
    caller_ids = {d.src_component_id for d in callers} - set(owned_ids)
    caller_entries = [_entry(id_to_comp[i]) for i in caller_ids if i in id_to_comp]

    tested_by = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == snapshot.id,
            Dependency.src_component_id == module.id,
            Dependency.kind == DependencyKind.TESTED_BY.value,
        )
    ).all()
    test_entries = [
        {"component_id": d.dst_component_id, "qualified_name": id_to_comp[d.dst_component_id].qualified_name}
        for d in tested_by
        if d.dst_component_id in id_to_comp
    ]

    changed_with = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == snapshot.id,
            Dependency.src_component_id == module.id,
            Dependency.kind == DependencyKind.CHANGED_WITH.value,
        )
    ).all()
    co_change_entries = [
        {
            "component_id": d.dst_component_id,
            "qualified_name": d.target_name,
            "count": (d.attributes or {}).get("count", 0),
            "confidence": (d.attributes or {}).get("confidence", 0.0),
        }
        for d in changed_with
    ]

    external = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == snapshot.id,
            Dependency.src_component_id.in_(owned_ids),
            Dependency.external.is_(True),
        )
    ).all()
    seen_targets: set[str] = set()
    external_entries = []
    for d in external:
        if d.target_name in seen_targets:
            continue
        seen_targets.add(d.target_name)
        external_entries.append({"target_name": d.target_name, "kind": d.kind.value})

    return {
        "direct_dependents": direct_entries,
        "indirect_dependents": indirect_entries,
        "callers": caller_entries,
        "related_tests": test_entries,
        "historical_co_changes": co_change_entries,
        "external_integrations": external_entries,
        "potential_impact": _potential_impact(direct_entries, test_entries, caller_entries),
    }


def compute_and_persist_change_impact(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, target: Component
) -> ChangeImpact:
    comps = session.scalars(
        select(Component).where(Component.snapshot_id == snapshot.id)
    ).all()
    comps_by_path: dict[str, list[Component]] = {}
    module_by_path: dict[str, Component] = {}
    for c in comps:
        comps_by_path.setdefault(c.path, []).append(c)
        if c.kind is ComponentKind.MODULE:
            module_by_path[c.path] = c
    mg = build_module_graph(session, snapshot.id)

    fields = _compute(session, snapshot, target, mg, comps_by_path, module_by_path)
    row = session.scalar(
        select(ChangeImpact).where(
            ChangeImpact.run_id == run.id, ChangeImpact.component_id == target.id
        )
    )
    if row is None:
        row = ChangeImpact(
            run_id=run.id, snapshot_id=snapshot.id, component_id=target.id,
            engine_version=CHANGE_IMPACT_VERSION, produced_by=CHANGE_IMPACT_VERSION,
        )
        session.add(row)
    for key, value in fields.items():
        setattr(row, key, value)
    session.flush()
    return row


def run_change_impact(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
) -> ChangeImpactSummary:
    comps = session.scalars(
        select(Component).where(Component.snapshot_id == snapshot.id)
    ).all()
    comps_by_path: dict[str, list[Component]] = {}
    module_by_path: dict[str, Component] = {}
    for c in comps:
        comps_by_path.setdefault(c.path, []).append(c)
        if c.kind is ComponentKind.MODULE:
            module_by_path[c.path] = c
    mg = build_module_graph(session, snapshot.id)

    computed = 0
    for module in module_by_path.values():
        fields = _compute(session, snapshot, module, mg, comps_by_path, module_by_path)
        row = session.scalar(
            select(ChangeImpact).where(
                ChangeImpact.run_id == run.id, ChangeImpact.component_id == module.id
            )
        )
        if row is None:
            row = ChangeImpact(
                run_id=run.id, snapshot_id=snapshot.id, component_id=module.id,
                engine_version=CHANGE_IMPACT_VERSION, produced_by=CHANGE_IMPACT_VERSION,
            )
            session.add(row)
        for key, value in fields.items():
            setattr(row, key, value)
        computed += 1
    session.flush()

    artifact = write_json(
        session, run.id, _ARTIFACT_KIND,
        {"schema": "archon.change_impact.v1", "snapshot_id": snapshot.id, "modules_computed": computed},
        stage=Stage.ANALYZING_CHANGE_IMPACT,
    )
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.ANALYZING_CHANGE_IMPACT, classification=Classification.FACT,
            summary=f"Computed change impact for {computed} module(s)",
            produced_by=CHANGE_IMPACT_VERSION, confidence=1.0,
        )
    )
    session.flush()
    log.info(
        "change impact computed",
        extra={"extra_fields": {"run_id": run.id, "computed": computed, "artifact": artifact.ref}},
    )
    return ChangeImpactSummary(computed=computed, reused=0)
