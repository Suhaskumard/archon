"""Build NetworkX graphs from the snapshot's components + dependencies (spec section 23).

* ``build_component_graph`` - every component is a node, every resolved dependency an edge
  (CONTAINS / IMPORTS / CALLS / INHERITS / DEPENDS_ON / TESTED_BY).
* ``build_module_graph`` - collapses to MODULE nodes: module A depends on module B when any
  component of A has a resolved IMPORTS / CALLS / INHERITS edge into a component of B.
"""

from __future__ import annotations

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.db.models import Component, Dependency
from archon.domain.enums import ComponentKind, DependencyKind

GRAPH_VERSION = "graph.v1"

_MODULE_EDGE_KINDS = {DependencyKind.IMPORTS, DependencyKind.CALLS, DependencyKind.INHERITS}


def _dep_kind(value) -> DependencyKind:
    return value if isinstance(value, DependencyKind) else DependencyKind(value)


def build_component_graph(session: Session, snapshot_id: str) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    comps = session.scalars(
        select(Component).where(Component.snapshot_id == snapshot_id)
    ).all()
    for c in comps:
        g.add_node(
            c.id,
            kind=c.kind.value,
            qualified_name=c.qualified_name,
            name=c.name,
            path=c.path,
            role=c.role,
            is_test=c.is_test,
            parent_id=c.parent_id,
            complexity=(c.metrics or {}).get("complexity"),
        )
    deps = session.scalars(
        select(Dependency).where(Dependency.snapshot_id == snapshot_id)
    ).all()
    for d in deps:
        if d.dst_component_id is None or not g.has_node(d.dst_component_id):
            continue
        g.add_edge(
            d.src_component_id,
            d.dst_component_id,
            key=d.id,
            kind=_dep_kind(d.kind).value,
            resolved=d.resolved,
            target_name=d.target_name,
        )
    return g


def build_module_graph(session: Session, snapshot_id: str) -> nx.DiGraph:
    comps = session.scalars(
        select(Component).where(Component.snapshot_id == snapshot_id)
    ).all()

    modules: dict[str, Component] = {}          # module_id -> Component
    owner: dict[str, str] = {}                  # any component_id -> owning module_id
    by_path: dict[str, str] = {}               # path -> module_id
    for c in comps:
        if c.kind is ComponentKind.MODULE:
            modules[c.id] = c
            by_path[c.path] = c.id
    for c in comps:
        if c.kind is ComponentKind.MODULE:
            owner[c.id] = c.id
        elif c.path in by_path:
            owner[c.id] = by_path[c.path]

    mg = nx.DiGraph()
    for mid, mc in modules.items():
        mg.add_node(
            mid,
            qualified_name=mc.qualified_name,
            name=mc.name,
            path=mc.path,
            role=mc.role,
            is_test=mc.is_test,
            is_entrypoint=mc.is_entrypoint,
        )

    deps = session.scalars(
        select(Dependency).where(Dependency.snapshot_id == snapshot_id)
    ).all()
    for d in deps:
        if _dep_kind(d.kind) not in _MODULE_EDGE_KINDS or d.dst_component_id is None:
            continue
        src_m = owner.get(d.src_component_id)
        dst_m = owner.get(d.dst_component_id)
        if not src_m or not dst_m or src_m == dst_m:
            continue
        if mg.has_edge(src_m, dst_m):
            e = mg.edges[src_m, dst_m]
            e["weight"] += 1
            e["kinds"].add(_dep_kind(d.kind).value)
        else:
            mg.add_edge(src_m, dst_m, weight=1, kinds={_dep_kind(d.kind).value})
    return mg


def module_id_by_qn(mg: nx.DiGraph) -> dict[str, str]:
    return {data["qualified_name"]: node for node, data in mg.nodes(data=True)}
