"""Phase 7 execution endpoints: discovered tests, sandboxed executions
(spec sections 12, 33, 36, 47)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.api.deps import get_session
from archon.api.schemas import ExecutionOut, TestCaseOut
from archon.core.artifacts import read_text
from archon.core.errors import ArchonError, ErrorCode
from archon.db.models import AnalysisArtifact, AnalysisRun, Execution, TestCase

router = APIRouter(tags=["execution"])

_PREVIEW_CHARS = 4000


def _run_with_snapshot(session: Session, run_id: str) -> AnalysisRun:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"run {run_id!r} not found")
    if run.snapshot_id is None:
        raise ArchonError(
            ErrorCode.CONFLICT, "run has no snapshot yet",
            suggested_action="Wait for the run to reach SNAPSHOTTING.",
        )
    return run


def _preview(session: Session, artifact_id: str | None) -> str:
    if artifact_id is None:
        return ""
    art = session.get(AnalysisArtifact, artifact_id)
    if art is None:
        return ""
    text = read_text(art)
    return text[-_PREVIEW_CHARS:]


@router.get("/runs/{run_id}/tests", response_model=list[TestCaseOut])
def list_tests(
    run_id: str,
    session: Session = Depends(get_session),
    kind: str | None = Query(default=None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> list[TestCaseOut]:
    _run_with_snapshot(session, run_id)
    stmt = select(TestCase).where(TestCase.run_id == run_id)
    if kind:
        stmt = stmt.where(TestCase.kind == kind.upper())
    rows = session.scalars(stmt.limit(limit).offset(offset)).all()
    return [
        TestCaseOut(
            id=r.id, component_id=r.component_id,
            kind=r.kind.value if hasattr(r.kind, "value") else r.kind,
            path=r.path, name=r.name,
            origin=r.origin.value if hasattr(r.origin, "value") else r.origin,
            validated=r.validated, validation_errors=r.validation_errors,
        )
        for r in rows
    ]


@router.get("/runs/{run_id}/executions", response_model=list[ExecutionOut])
def list_executions(
    run_id: str,
    session: Session = Depends(get_session),
    kind: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[ExecutionOut]:
    _run_with_snapshot(session, run_id)
    stmt = select(Execution).where(Execution.run_id == run_id)
    if kind:
        stmt = stmt.where(Execution.kind == kind.upper())
    rows = session.scalars(
        stmt.order_by(Execution.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return [
        ExecutionOut(
            id=r.id, kind=r.kind.value if hasattr(r.kind, "value") else r.kind,
            command=r.command, exit_code=r.exit_code, passed=r.passed, failed=r.failed,
            errors=r.errors, timed_out=r.timed_out, duration_ms=r.duration_ms,
            stdout_preview=_preview(session, r.stdout_ref),
            stderr_preview=_preview(session, r.stderr_ref),
            stdout_ref=r.stdout_ref, stderr_ref=r.stderr_ref, coverage_ref=r.coverage_ref,
            started_at=r.started_at, ended_at=r.ended_at,
        )
        for r in rows
    ]
