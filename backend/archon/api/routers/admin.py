"""Operability endpoints: Prometheus metrics, readiness, and the ops run view (spec section 55)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archon.api.deps import get_session
from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.observability import metrics, render_metrics
from archon.db.migrate import current_revision, head_revision
from archon.db.models import AnalysisRun, Evidence, Job, Repository, RepositorySnapshot
from archon.domain.enums import JobState, RunState

router = APIRouter(tags=["admin"])


def _refresh_queue_gauges(session: Session) -> None:
    counts = dict(
        session.execute(select(Job.state, func.count(Job.id)).group_by(Job.state)).all()
    )
    metrics.jobs_queued.set(int(counts.get(JobState.QUEUED, 0)))
    metrics.jobs_running.set(int(counts.get(JobState.RUNNING, 0)))
    metrics.runs_active.set(
        int(session.scalar(select(func.count(AnalysisRun.id)).where(
            AnalysisRun.state == RunState.RUNNING
        )) or 0)
    )


@router.get("/metrics")
def prometheus_metrics(session: Session = Depends(get_session)) -> Response:
    _refresh_queue_gauges(session)
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


@router.get("/readyz", tags=["meta"])
def readyz(session: Session = Depends(get_session)) -> dict:
    """Readiness: DB reachable AND migrations at head. 503 otherwise."""
    try:
        session.execute(select(1))
    except Exception as exc:  # pragma: no cover - only on a real outage
        raise ArchonError(
            ErrorCode.INTERNAL, "database is not reachable",
            recoverability=Recoverability.TRANSIENT,
        ) from exc
    at, head = current_revision(), head_revision()
    if at != head:
        raise ArchonError(
            ErrorCode.INTERNAL,
            f"database schema is behind (at {at!r}, head {head!r})",
            recoverability=Recoverability.TRANSIENT,
            suggested_action="Run `archon db-upgrade`.",
        )
    return {"status": "ready", "revision": at}


@router.get("/admin/runs")
def admin_runs(
    session: Session = Depends(get_session),
    state: RunState | None = Query(default=None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Operational view: one row per run with repo / snapshot / timing / AI activity."""
    stmt = select(AnalysisRun).order_by(AnalysisRun.created_at.desc())
    if state is not None:
        stmt = stmt.where(AnalysisRun.state == state)
    runs = session.scalars(stmt.limit(limit).offset(offset)).all()

    repo_ids = {r.repository_id for r in runs}
    snap_ids = {r.snapshot_id for r in runs if r.snapshot_id}
    repos = {
        r.id: r for r in session.scalars(
            select(Repository).where(Repository.id.in_(repo_ids))
        ).all()
    } if repo_ids else {}
    snaps = {
        s.id: s for s in session.scalars(
            select(RepositorySnapshot).where(RepositorySnapshot.id.in_(snap_ids))
        ).all()
    } if snap_ids else {}

    # AI activity per run: count Evidence rows whose produced_by names an AI provider.
    ai_by_run: dict[str, int] = {}
    if runs:
        rows = session.execute(
            select(Evidence.run_id, func.count(Evidence.id))
            .where(
                Evidence.run_id.in_([r.id for r in runs]),
                Evidence.produced_by.like("claude:%"),
            )
            .group_by(Evidence.run_id)
        ).all()
        ai_by_run = {run_id: int(n) for run_id, n in rows}

    now = datetime.now(UTC)
    items = []
    for r in runs:
        snap = snaps.get(r.snapshot_id)
        end = r.ended_at or (now if r.state == RunState.RUNNING else None)
        dur = (end - r.started_at).total_seconds() if (r.started_at and end) else None
        items.append({
            "run_id": r.id,
            "repository": getattr(repos.get(r.repository_id), "url", None),
            "snapshot_id": r.snapshot_id,
            "commit_sha": getattr(snap, "commit_sha", None),
            "mode": r.mode.value,
            "state": r.state.value,
            "current_stage": r.current_stage.value if r.current_stage else None,
            "last_completed_stage": (
                r.last_completed_stage.value if r.last_completed_stage else None
            ),
            "trigger": (r.trigger or {}).get("source", "api"),
            "started_at": r.started_at,
            "ended_at": r.ended_at,
            "duration_seconds": round(dur, 1) if dur is not None else None,
            "progress_pct": r.progress_pct,
            "error": r.error,
            "ai_evidence_count": ai_by_run.get(r.id, 0),
        })
    return {"total": len(items), "runs": items}
