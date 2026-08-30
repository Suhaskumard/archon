"""Architecture reconstruction stage (spec section 23).

Infers a role for every module, computes coupling/centrality metrics on the module graph,
mirrors the module role onto its child components, persists everything, writes the
``architecture_graph`` artifact, and emits classified evidence. Deterministic; results are
cached on the snapshot (roles + metrics live on ``Component``).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import networkx as nx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archon.analysis.architecture.metrics import METRICS_VERSION, module_metrics
from archon.analysis.architecture.roles import (
    RoleContext,
    infer_role,
    layering_violation,
)
from archon.analysis.graph.builder import build_component_graph, build_module_graph
from archon.core.artifacts import write_json
from archon.core.logging import get_logger
from archon.db.models import AnalysisRun, Component, Evidence, RepositorySnapshot
from archon.domain.enums import Classification, ComponentKind, Stage

log = get_logger("archon.analysis.architecture")

ARCHITECTURE_VERSION = "architecture.v1"
_GRAPH_ARTIFACT_KIND = "architecture_graph"
_TOP_HUBS = 5


@dataclass
class ArchitectureSummary:
    reused: bool
    module_count: int
    roles: dict[str, int]
    depends_on_edges: int
    cycles: int
    layering_violations: list[dict]
    top_hubs: list[dict] = field(default_factory=list)
    artifact_ref: str | None = None

    def as_dict(self) -> dict:
        return {
            "reused": self.reused,
            "modules": self.module_count,
            "roles": self.roles,
            "depends_on_edges": self.depends_on_edges,
            "cycles": self.cycles,
            "layering_violations": self.layering_violations,
            "top_hubs": self.top_hubs,
            "artifact": self.artifact_ref,
        }


def _role_contexts(session: Session, snapshot_id: str, mg: nx.DiGraph) -> dict[str, RoleContext]:
    comps = session.scalars(
        select(Component).where(Component.snapshot_id == snapshot_id)
    ).all()
    modules = {c.id: c for c in comps if c.kind is ComponentKind.MODULE}
    children_by_parent: dict[str, list[Component]] = {}
    for c in comps:
        if c.parent_id:
            children_by_parent.setdefault(c.parent_id, []).append(c)

    # import roots per module: from IMPORTS dependency rows (target_name), resolved or not
    from archon.db.models import Dependency
    from archon.domain.enums import DependencyKind

    import_roots: dict[str, set[str]] = {mid: set() for mid in modules}
    deps = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == snapshot_id,
            Dependency.kind == DependencyKind.IMPORTS.value,
        )
    ).all()
    for d in deps:
        if d.src_component_id in import_roots and d.target_name:
            import_roots[d.src_component_id].add(d.target_name.split(".")[0])

    ctxs: dict[str, RoleContext] = {}
    for mid, mc in modules.items():
        kids = children_by_parent.get(mid, [])
        class_count = sum(1 for k in kids if k.kind is ComponentKind.CLASS)
        func_count = sum(1 for k in kids if k.kind is ComponentKind.FUNCTION)
        decorators: list[str] = []
        for k in kids:
            decorators += (k.metrics or {}).get("decorators", [])
            for gk in children_by_parent.get(k.id, []):  # class methods
                decorators += (gk.metrics or {}).get("decorators", [])
        ctxs[mid] = RoleContext(
            qualified_name=mc.qualified_name,
            name=mc.name,
            path=mc.path,
            is_test=mc.is_test,
            is_entrypoint=mc.is_entrypoint,
            class_count=class_count,
            function_count=func_count,
            import_roots=import_roots.get(mid, set()),
            decorator_names=decorators,
            in_internal_graph=mid in mg and mg.degree(mid) > 0,
        )
    return ctxs


def _already_reconstructed(session: Session, snapshot_id: str) -> bool:
    total = session.scalar(
        select(func.count(Component.id)).where(
            Component.snapshot_id == snapshot_id, Component.kind == ComponentKind.MODULE
        )
    )
    if not total:
        return False
    with_role = session.scalar(
        select(func.count(Component.id)).where(
            Component.snapshot_id == snapshot_id,
            Component.kind == ComponentKind.MODULE,
            Component.role.is_not(None),
        )
    )
    if with_role != total:
        return False
    sample = session.scalar(
        select(Component).where(
            Component.snapshot_id == snapshot_id, Component.kind == ComponentKind.MODULE
        )
    )
    return bool(sample and "architecture" in (sample.metrics or {}))


def reconstruct_architecture(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
) -> ArchitectureSummary:
    mg = build_module_graph(session, snapshot.id)
    metrics = module_metrics(mg)
    reused = _already_reconstructed(session, snapshot.id)

    ctxs = _role_contexts(session, snapshot.id, mg)
    role_by_id = {mid: infer_role(ctx) for mid, ctx in ctxs.items()}
    role_by_path = {ctxs[mid].path: role for mid, role in role_by_id.items()}

    if not reused:
        comps = session.scalars(
            select(Component).where(Component.snapshot_id == snapshot.id)
        ).all()
        for c in comps:
            if c.is_config:
                c.role = "config"
            elif c.path in role_by_path:
                c.role = role_by_path[c.path]
            if c.kind is ComponentKind.MODULE and c.id in metrics:
                m = dict(c.metrics or {})
                m["architecture"] = {**metrics[c.id], "role": role_by_id.get(c.id),
                                     "metrics_model": METRICS_VERSION}
                c.metrics = m
        session.flush()

    roles = dict(Counter(role_by_id.values()))
    qn_of = {mid: ctxs[mid].qualified_name for mid in ctxs}

    violations: list[dict] = []
    for u, v in mg.edges():
        why = layering_violation(role_by_id.get(u), role_by_id.get(v))
        if why:
            violations.append(
                {"from": qn_of.get(u), "from_role": role_by_id.get(u),
                 "to": qn_of.get(v), "to_role": role_by_id.get(v), "reason": why}
            )

    top_hubs = sorted(
        (
            {"qualified_name": qn_of.get(mid),
             "role": role_by_id.get(mid),
             "betweenness": metrics.get(mid, {}).get("betweenness_centrality", 0.0),
             "fan_in": metrics.get(mid, {}).get("fan_in", 0),
             "fan_out": metrics.get(mid, {}).get("fan_out", 0)}
            for mid in mg.nodes
        ),
        key=lambda h: (h["betweenness"], h["fan_in"]),
        reverse=True,
    )[:_TOP_HUBS]

    cg = build_component_graph(session, snapshot.id)
    from archon.analysis.graph.derive import find_cycles

    cycles = find_cycles(mg)
    artifact = write_json(
        session, run.id, _GRAPH_ARTIFACT_KIND,
        {
            "schema": "archon.graph.v1",
            "snapshot_id": snapshot.id,
            "roles": {qn_of[mid]: role for mid, role in role_by_id.items()},
            "module_metrics": {qn_of[mid]: metrics.get(mid, {}) for mid in ctxs},
            "cycles": cycles,
            "layering_violations": violations,
            "components": nx.node_link_data(cg, edges="links"),
            "modules": nx.node_link_data(_relabel(mg, qn_of), edges="links"),
        },
        stage=Stage.RECONSTRUCTING_ARCHITECTURE,
    )

    _emit_evidence(session, run, roles, top_hubs, violations, reused)
    log.info(
        "architecture reconstructed",
        extra={"extra_fields": {"run_id": run.id, "roles": roles,
                                "violations": len(violations), "reused": reused}},
    )
    return ArchitectureSummary(
        reused=reused,
        module_count=mg.number_of_nodes(),
        roles=roles,
        depends_on_edges=mg.number_of_edges(),
        cycles=len(cycles),
        layering_violations=violations,
        top_hubs=top_hubs,
        artifact_ref=artifact.ref,
    )


def _relabel(mg: nx.DiGraph, qn_of: dict[str, str]) -> nx.DiGraph:
    h = nx.DiGraph()
    for node, data in mg.nodes(data=True):
        h.add_node(qn_of.get(node, node), **{k: v for k, v in data.items()})
    for u, v, data in mg.edges(data=True):
        h.add_edge(qn_of.get(u, u), qn_of.get(v, v),
                   weight=data.get("weight", 1), kinds=sorted(data.get("kinds", [])))
    return h


def _emit_evidence(
    session: Session,
    run: AnalysisRun,
    roles: dict[str, int],
    top_hubs: list[dict],
    violations: list[dict],
    reused: bool,
) -> None:
    role_str = ", ".join(f"{k}={v}" for k, v in sorted(roles.items()))
    prefix = "Reused cached architecture" if reused else "Reconstructed architecture"
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.RECONSTRUCTING_ARCHITECTURE,
            classification=Classification.FACT,
            summary=f"{prefix}: {sum(roles.values())} modules ({role_str})",
            produced_by=ARCHITECTURE_VERSION, confidence=1.0,
            refs={"roles": roles},
        )
    )
    if top_hubs and top_hubs[0]["betweenness"] > 0:
        names = ", ".join(f"{h['qualified_name']} ({h['betweenness']:.2f})" for h in top_hubs[:3])
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.RECONSTRUCTING_ARCHITECTURE,
                classification=Classification.FACT,
                summary=f"Central modules by betweenness: {names}",
                produced_by=ARCHITECTURE_VERSION, refs={"top_hubs": top_hubs},
            )
        )
    for v in violations[:20]:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.RECONSTRUCTING_ARCHITECTURE,
                classification=Classification.INFERENCE,
                summary=f"Layering: {v['from']} -> {v['to']} ({v['reason']})",
                detail=f"{v['from_role']} -> {v['to_role']}",
                produced_by=ARCHITECTURE_VERSION, confidence=0.7,
            )
        )
    session.flush()
