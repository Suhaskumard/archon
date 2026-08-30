"""Deterministic behaviour assembly for one component (spec section 24).

Pulls from the AST metrics (Phase 2), the dependency graph (Phase 2/3) and the git
metrics (Phase 4). No code is executed; observed structure is NOT assumed correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.db.models import Component, Dependency
from archon.domain.enums import ComponentKind, DependencyKind

BEHAVIOR_VERSION = "behavior.v1"

_IO_ROLES = {"io", "model"}


@dataclass
class BehaviorFacts:
    component_id: str
    qualified_name: str
    kind: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    callers: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    likely_invariants: list[str] = field(default_factory=list)
    git: dict = field(default_factory=dict)
    docstring: str | None = None


def _dep_kind(v) -> DependencyKind:
    return v if isinstance(v, DependencyKind) else DependencyKind(v)


def reconstruct_behavior(
    session: Session,
    snapshot_id: str,
    component: Component,
    *,
    assumptions_by_fn: dict[str, list] | None = None,
) -> BehaviorFacts:
    metrics = component.metrics or {}
    facts = BehaviorFacts(
        component_id=component.id,
        qualified_name=component.qualified_name,
        kind=component.kind.value,
        git=metrics.get("git", {}) or {},
        docstring=metrics.get("docstring"),
    )

    if component.kind in (ComponentKind.FUNCTION, ComponentKind.METHOD):
        args = metrics.get("args", [])
        ret = metrics.get("returns_annotation")
        facts.inputs = [a for a in args if a not in ("self", "cls")]
        if ret:
            facts.outputs = [f"{ret}"]
        elif metrics.get("is_generator"):
            facts.outputs = ["<generator>"]
        else:
            facts.outputs = ["<value>"]
        facts.exceptions = list(metrics.get("raises", []))
        if metrics.get("is_async"):
            facts.side_effects.append("async coroutine")
        if metrics.get("is_generator"):
            facts.side_effects.append("lazy generator")
    elif component.kind is ComponentKind.MODULE:
        facts.inputs = []
        facts.outputs = []

    # call edges
    out_edges = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == snapshot_id,
            Dependency.src_component_id == component.id,
            Dependency.kind == DependencyKind.CALLS.value,
        )
    ).all()
    in_edges = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == snapshot_id,
            Dependency.dst_component_id == component.id,
            Dependency.kind == DependencyKind.CALLS.value,
        )
    ).all()

    dst_ids = [e.dst_component_id for e in out_edges if e.dst_component_id]
    src_ids = [e.src_component_id for e in in_edges]
    id_to_comp = {
        c.id: c
        for c in session.scalars(
            select(Component).where(Component.id.in_(dst_ids + src_ids))
        ).all()
    }
    facts.callees = sorted({id_to_comp[i].qualified_name for i in dst_ids if i in id_to_comp})
    facts.callers = sorted({id_to_comp[i].qualified_name for i in src_ids if i in id_to_comp})

    for i in dst_ids:
        c = id_to_comp.get(i)
        if c and c.role in _IO_ROLES:
            facts.side_effects.append(f"calls {c.qualified_name} ({c.role})")
        if c:
            facts.exceptions.extend(
                e for e in (c.metrics or {}).get("raises", []) if e not in facts.exceptions
            )

    # tests: TESTED_BY on the owning module + test-module callers
    module = component
    if component.kind not in (ComponentKind.MODULE, ComponentKind.FILE):
        module = session.scalar(
            select(Component).where(
                Component.snapshot_id == snapshot_id,
                Component.kind == ComponentKind.MODULE,
                Component.path == component.path,
            )
        ) or component
    tested_by = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == snapshot_id,
            Dependency.src_component_id == module.id,
            Dependency.kind == DependencyKind.TESTED_BY.value,
        )
    ).all()
    facts.tests = sorted({e.target_name for e in tested_by})
    facts.tests += sorted(qn for qn in facts.callers if ".test_" in qn or qn.split(".")[-1].startswith("test_"))

    # assumptions attached to this function become invariant hints
    for a in (assumptions_by_fn or {}).get(component.qualified_name, []):
        facts.likely_invariants.append(f"assumes: {a.description}")

    # dedupe, preserve order
    facts.side_effects = _dedupe(facts.side_effects)
    facts.exceptions = _dedupe(facts.exceptions)
    facts.tests = _dedupe(facts.tests)
    return facts


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
