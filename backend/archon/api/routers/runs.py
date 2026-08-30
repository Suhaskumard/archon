"""Analysis-run status endpoints (spec sections 47, 55)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.api.deps import get_session
from archon.api.schemas import EvidenceOut, RunOut
from archon.api.serialize import evidence_out, run_out
from archon.core.errors import ArchonError, ErrorCode
from archon.db.models import AnalysisRun
from archon.domain.enums import RunState
from archon.jobs.manager import JobManager

router = APIRouter(prefix="/runs", tags=["runs"])
_jobs = JobManager()


def _load(session: Session, run_id: str) -> AnalysisRun:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise ArchonError(
            ErrorCode.NOT_FOUND,
            f"run {run_id!r} not found",
            suggested_action="List runs for the repository to find a valid id.",
        )
    return run


@router.get("", response_model=list[RunOut])
def list_runs(
    session: Session = Depends(get_session),
    state: RunState | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[RunOut]:
    stmt = select(AnalysisRun).order_by(AnalysisRun.created_at.desc())
    if state is not None:
        stmt = stmt.where(AnalysisRun.state == state)
    rows = session.scalars(stmt.limit(limit).offset(offset)).all()
    return [run_out(r, include_children=False) for r in rows]


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: str, session: Session = Depends(get_session)) -> RunOut:
    return run_out(_load(session, run_id))


@router.get("/{run_id}/evidence", response_model=list[EvidenceOut])
def get_run_evidence(run_id: str, session: Session = Depends(get_session)) -> list[EvidenceOut]:
    run = _load(session, run_id)
    return [evidence_out(e) for e in sorted(run.evidence, key=lambda x: x.created_at)]


@router.post("/{run_id}/cancel", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def cancel_run(run_id: str, session: Session = Depends(get_session)) -> RunOut:
    run = _load(session, run_id)
    _jobs.request_cancel(session, run.id)
    session.flush()
    session.refresh(run)
    return run_out(run)
