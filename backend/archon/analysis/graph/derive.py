"""Derive & persist module-level edges (spec section 23).

``DEPENDS_ON``  - one edge per module_graph edge (module A -> module B).
``TESTED_BY``   - for a test module T that depends on non-test module M, an edge M -> T.

Idempotent per snapshot: existing DEPENDS_ON / TESTED_BY rows are deleted first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
from sqlalchemy import delete
from sqlalchemy.orm import Session

from archon.analysis.graph.builder import build_module_graph
from archon.core.logging import get_logger
from archon.db.models import Dependency, RepositorySnapshot
from archon.domain.enums import DependencyKind

log = get_logger("archon.analysis.graph")

_MAX_CYCLES = 50


@dataclass
class DeriveResult:
    module_graph: nx.DiGraph
    depends_on_edges: int = 0
    tested_by_edges: int = 0
    cycles: list[list[str]] = field(default_factory=list)


def find_cycles(mg: nx.DiGraph) -> list[list[str]]:
    """Return import cycles as lists of module qualified names (self-loops included)."""
    out: list[list[str]] = []
    for scc in nx.strongly_connected_components(mg):
        if len(scc) < 2:
            continue
        sub = mg.subgraph(scc)
        for cycle in nx.simple_cycles(sub):
            out.append([mg.nodes[n]["qualified_name"] for n in cycle])
            if len(out) >= _MAX_CYCLES:
                return out
    for node in mg.nodes:
        if mg.has_edge(node, node):
            out.append([mg.nodes[node]["qualified_name"]])
    return out


def derive_edges(session: Session, snapshot: RepositorySnapshot) -> DeriveResult:
    session.execute(
        delete(Dependency).where(
            Dependency.snapshot_id == snapshot.id,
            Dependency.kind.in_([DependencyKind.DEPENDS_ON.value, DependencyKind.TESTED_BY.value]),
        )
    )
    session.flush()

    mg = build_module_graph(session, snapshot.id)
    depends_on = 0
    tested_by = 0

    for src_m, dst_m, data in mg.edges(data=True):
        session.add(
            Dependency(
                snapshot_id=snapshot.id,
                kind=DependencyKind.DEPENDS_ON,
                src_component_id=src_m,
                dst_component_id=dst_m,
                target_name=mg.nodes[dst_m]["qualified_name"],
                resolved=True,
                external=False,
                attributes={"weight": data["weight"], "kinds": sorted(data["kinds"])},
            )
        )
        depends_on += 1
        if mg.nodes[src_m]["is_test"] and not mg.nodes[dst_m]["is_test"]:
            session.add(
                Dependency(
                    snapshot_id=snapshot.id,
                    kind=DependencyKind.TESTED_BY,
                    src_component_id=dst_m,             # the tested module
                    dst_component_id=src_m,             # the test module
                    target_name=mg.nodes[src_m]["qualified_name"],
                    resolved=True,
                    external=False,
                    attributes={"via": sorted(data["kinds"])},
                )
            )
            tested_by += 1

    session.flush()
    cycles = find_cycles(mg)
    log.info(
        "module edges derived",
        extra={"extra_fields": {
            "snapshot_id": snapshot.id,
            "depends_on": depends_on,
            "tested_by": tested_by,
            "cycles": len(cycles),
        }},
    )
    return DeriveResult(
        module_graph=mg, depends_on_edges=depends_on, tested_by_edges=tested_by, cycles=cycles
    )
