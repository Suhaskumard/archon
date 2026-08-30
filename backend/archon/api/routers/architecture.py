"""Architecture & dependency-graph endpoints (spec sections 23, 47)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.api.deps import get_session
from archon.api.schemas import ArchitectureOut, ModuleArchOut
from archon.core.artifacts import read_json
from archon.core.errors import ArchonError, ErrorCode
from archon.db.models import AnalysisArtifact, AnalysisRun, Component, RepositorySnapshot
from archon.domain.enums import ComponentKind

router = APIRouter(tags=["architecture"])

_GRAPH_ARTIFACT_KIND = "architecture_graph"


def _require_run(session: Session, run_id: str) -> AnalysisRun:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"run {run_id!r} not found")
    if run.snapshot_id is None:
        raise ArchonError(
            ErrorCode.CONFLICT,
            "run has no snapshot yet",
            suggested_action="Wait for the run to reach SNAPSHOTTING.",
        )
    return run


def _graph_artifact(session: Session, run_id: str) -> AnalysisArtifact:
    art = session.scalar(
        select(AnalysisArtifact).where(
            AnalysisArtifact.run_id == run_id,
            AnalysisArtifact.kind == _GRAPH_ARTIFACT_KIND,
        )
    )
    if art is None:
        raise ArchonError(
            ErrorCode.CONFLICT,
            "architecture has not been reconstructed for this run",
            suggested_action="Run the analysis in ANALYSIS_ONLY or FULL mode.",
        )
    return art


def _module_rows(session: Session, snapshot_id: str) -> list[ModuleArchOut]:
    mods = session.scalars(
        select(Component).where(
            Component.snapshot_id == snapshot_id, Component.kind == ComponentKind.MODULE
        ).order_by(Component.qualified_name)
    ).all()
    out: list[ModuleArchOut] = []
    for m in mods:
        arch = (m.metrics or {}).get("architecture", {})
        out.append(
            ModuleArchOut(
                id=m.id,
                qualified_name=m.qualified_name,
                path=m.path,
                role=m.role,
                is_test=m.is_test,
                is_entrypoint=m.is_entrypoint,
                fan_in=arch.get("fan_in", 0),
                fan_out=arch.get("fan_out", 0),
                instability=arch.get("instability", 0.0),
                degree_centrality=arch.get("degree_centrality", 0.0),
                betweenness_centrality=arch.get("betweenness_centrality", 0.0),
                pagerank=arch.get("pagerank", 0.0),
                in_cycle=arch.get("in_cycle", False),
                scc_size=arch.get("scc_size", 1),
                dependents=arch.get("dependents", []),
                dependencies=arch.get("dependencies", []),
            )
        )
    return out


@router.get("/runs/{run_id}/architecture", response_model=ArchitectureOut)
def get_architecture(run_id: str, session: Session = Depends(get_session)) -> ArchitectureOut:
    run = _require_run(session, run_id)
    art = _graph_artifact(session, run_id)
    doc = read_json(art)
    modules = _module_rows(session, run.snapshot_id)
    roles: dict[str, int] = {}
    for m in modules:
        roles[m.role or "unknown"] = roles.get(m.role or "unknown", 0) + 1
    top_hubs = sorted(
        (
            {"qualified_name": m.qualified_name, "role": m.role,
             "betweenness": m.betweenness_centrality, "fan_in": m.fan_in, "fan_out": m.fan_out}
            for m in modules
        ),
        key=lambda h: (h["betweenness"], h["fan_in"]),
        reverse=True,
    )[:5]
    return ArchitectureOut(
        run_id=run_id,
        snapshot_id=run.snapshot_id,
        reconstructed=True,
        roles=roles,
        modules=modules,
        cycles=doc.get("cycles", []),
        layering_violations=doc.get("layering_violations", []),
        top_hubs=top_hubs,
        artifact_ref=art.ref,
    )


@router.get("/runs/{run_id}/architecture/graph")
def get_architecture_graph(run_id: str, session: Session = Depends(get_session)) -> dict:
    _require_run(session, run_id)
    return read_json(_graph_artifact(session, run_id))


@router.get("/snapshots/{snapshot_id}/modules", response_model=list[ModuleArchOut])
def list_modules(
    snapshot_id: str,
    session: Session = Depends(get_session),
    role: str | None = Query(default=None),
    in_cycle: bool | None = Query(default=None),
) -> list[ModuleArchOut]:
    if session.get(RepositorySnapshot, snapshot_id) is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"snapshot {snapshot_id!r} not found")
    rows = _module_rows(session, snapshot_id)
    if role is not None:
        rows = [m for m in rows if m.role == role]
    if in_cycle is not None:
        rows = [m for m in rows if m.in_cycle == in_cycle]
    return rows
