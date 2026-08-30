"""Source-intelligence endpoints (spec sections 22, 47)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archon.api.deps import get_session
from archon.api.schemas import ComponentOut, DependencyOut, SourceSummaryOut
from archon.api.serialize import component_out, dependency_out
from archon.core.errors import ArchonError, ErrorCode
from archon.db.models import AnalysisRun, Component, Dependency, RepositorySnapshot
from archon.domain.enums import ComponentKind, DependencyKind

router = APIRouter(tags=["source"])


def _require_snapshot(session: Session, snapshot_id: str) -> RepositorySnapshot:
    snap = session.get(RepositorySnapshot, snapshot_id)
    if snap is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"snapshot {snapshot_id!r} not found")
    return snap


@router.get("/snapshots/{snapshot_id}/components", response_model=list[ComponentOut])
def list_components(
    snapshot_id: str,
    session: Session = Depends(get_session),
    kind: ComponentKind | None = Query(default=None),
    path: str | None = Query(default=None, description="exact repo-relative path"),
    is_test: bool | None = Query(default=None),
    is_entrypoint: bool | None = Query(default=None),
    q: str | None = Query(default=None, description="substring match on qualified_name"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[ComponentOut]:
    _require_snapshot(session, snapshot_id)
    stmt = select(Component).where(Component.snapshot_id == snapshot_id)
    if kind is not None:
        stmt = stmt.where(Component.kind == kind)
    if path is not None:
        stmt = stmt.where(Component.path == path)
    if q:
        stmt = stmt.where(Component.qualified_name.contains(q))
    if is_test is not None:
        stmt = stmt.where(Component.is_test.is_(is_test))
    if is_entrypoint is not None:
        stmt = stmt.where(Component.is_entrypoint.is_(is_entrypoint))
    stmt = stmt.order_by(Component.path, Component.start_line).limit(limit).offset(offset)
    return [component_out(c) for c in session.scalars(stmt).all()]


@router.get("/components/{component_id}", response_model=ComponentOut)
def get_component(component_id: str, session: Session = Depends(get_session)) -> ComponentOut:
    c = session.get(Component, component_id)
    if c is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"component {component_id!r} not found")
    out = component_out(c)
    out.attributes = {
        **out.attributes,
        "child_count": session.scalar(
            select(func.count(Component.id)).where(Component.parent_id == component_id)
        ),
        "outgoing_edges": session.scalar(
            select(func.count(Dependency.id)).where(Dependency.src_component_id == component_id)
        ),
        "incoming_edges": session.scalar(
            select(func.count(Dependency.id)).where(Dependency.dst_component_id == component_id)
        ),
    }
    return out


@router.get("/snapshots/{snapshot_id}/dependencies", response_model=list[DependencyOut])
def list_dependencies(
    snapshot_id: str,
    session: Session = Depends(get_session),
    kind: DependencyKind | None = Query(default=None),
    resolved: bool | None = Query(default=None),
    external: bool | None = Query(default=None),
    src: str | None = Query(default=None, description="src component id"),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> list[DependencyOut]:
    _require_snapshot(session, snapshot_id)
    stmt = select(Dependency).where(Dependency.snapshot_id == snapshot_id)
    if kind is not None:
        stmt = stmt.where(Dependency.kind == kind)
    if resolved is not None:
        stmt = stmt.where(Dependency.resolved.is_(resolved))
    if external is not None:
        stmt = stmt.where(Dependency.external.is_(external))
    if src is not None:
        stmt = stmt.where(Dependency.src_component_id == src)
    stmt = stmt.order_by(Dependency.kind).limit(limit).offset(offset)
    return [dependency_out(d) for d in session.scalars(stmt).all()]


@router.get("/runs/{run_id}/source", response_model=SourceSummaryOut)
def run_source_summary(run_id: str, session: Session = Depends(get_session)) -> SourceSummaryOut:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"run {run_id!r} not found")
    if run.snapshot_id is None:
        raise ArchonError(
            ErrorCode.CONFLICT,
            "run has no snapshot yet",
            suggested_action="Wait for the run to reach SNAPSHOTTING.",
        )
    sid = run.snapshot_id

    comp_rows = session.execute(
        select(Component.kind, func.count(Component.id))
        .where(Component.snapshot_id == sid)
        .group_by(Component.kind)
    ).all()
    components = {k.value: 0 for k in ComponentKind}
    for kind, n in comp_rows:
        components[getattr(kind, "value", str(kind))] = n

    edge_rows = session.execute(
        select(Dependency.kind, func.count(Dependency.id))
        .where(Dependency.snapshot_id == sid)
        .group_by(Dependency.kind)
    ).all()
    edges = {k.value: 0 for k in DependencyKind}
    for kind, n in edge_rows:
        edges[getattr(kind, "value", str(kind))] = n
    edges["resolved"] = int(
        session.scalar(
            select(func.count(Dependency.id)).where(
                Dependency.snapshot_id == sid, Dependency.resolved.is_(True)
            )
        )
        or 0
    )

    entrypoints = session.scalars(
        select(Component).where(
            Component.snapshot_id == sid, Component.is_entrypoint.is_(True)
        )
    ).all()
    tests = session.scalar(
        select(func.count(Component.id)).where(
            Component.snapshot_id == sid,
            Component.kind == ComponentKind.MODULE,
            Component.is_test.is_(True),
        )
    )
    config_files = session.scalar(
        select(func.count(Component.id)).where(
            Component.snapshot_id == sid,
            Component.kind == ComponentKind.FILE,
            Component.is_config.is_(True),
        )
    )
    return SourceSummaryOut(
        snapshot_id=sid,
        analyzed=sum(components.values()) > 0,
        components=components,
        edges=edges,
        entrypoints=[component_out(c) for c in entrypoints],
        tests=int(tests or 0),
        config_files=int(config_files or 0),
    )
