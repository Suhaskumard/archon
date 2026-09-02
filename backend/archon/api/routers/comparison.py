"""Phase 11 repository-comparison endpoints (spec sections 45, 47).

Comparison is cross-run and on-demand: ``POST`` computes (or returns the cached) diff
between two analysis-scored runs of one repository, mirroring ``POST
/runs/{id}/change-impact``. No pipeline stage is involved.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.api.deps import get_session
from archon.api.schemas import ComparisonCreate, ComparisonOut, ComparisonSummaryOut
from archon.comparison import build_comparison
from archon.core.errors import ArchonError, ErrorCode
from archon.db.models import AnalysisRun, Repository, RepositoryComparison
from archon.domain.enums import Stage
from archon.pipeline.orchestrator import _ANALYSIS_STAGES

router = APIRouter(tags=["comparison"])

# Comparison needs architecture + Legacy DNA + tech debt + change safety, all of which
# are persisted by ``ASSESSING_CHANGE_SAFETY``. A run that reached that stage is
# comparable even if a later MVP-loop stage (execution/healing) failed the run.
_MIN_STAGE_INDEX = _ANALYSIS_STAGES.index(Stage.ASSESSING_CHANGE_SAFETY)


def _summary_out(r: RepositoryComparison) -> ComparisonSummaryOut:
    return ComparisonSummaryOut(
        id=r.id, repo_id=r.repo_id, base_run_id=r.base_run_id, head_run_id=r.head_run_id,
        base_snapshot_id=r.base_snapshot_id, head_snapshot_id=r.head_snapshot_id,
        base_commit_sha=r.base_commit_sha, head_commit_sha=r.head_commit_sha,
        summary=r.summary, produced_by=r.produced_by, created_at=r.created_at,
    )


def _full_out(r: RepositoryComparison) -> ComparisonOut:
    return ComparisonOut(
        **_summary_out(r).model_dump(),
        report=r.report, report_artifact_id=r.report_artifact_id,
    )


def _load_run(session: Session, repo_id: str, run_id: str, label: str) -> AnalysisRun:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"{label} run {run_id!r} not found")
    if run.repository_id != repo_id:
        raise ArchonError(
            ErrorCode.CONFLICT,
            f"{label} run {run_id!r} does not belong to repository {repo_id!r}",
        )
    if run.snapshot_id is None:
        raise ArchonError(
            ErrorCode.CONFLICT,
            f"{label} run {run_id!r} has no snapshot yet",
            suggested_action="Wait for the run to reach SNAPSHOTTING before comparing.",
        )
    stage = run.last_completed_stage
    if stage is None or stage not in _ANALYSIS_STAGES or _ANALYSIS_STAGES.index(stage) < _MIN_STAGE_INDEX:
        raise ArchonError(
            ErrorCode.CONFLICT,
            f"{label} run {run_id!r} has not finished analysis scoring yet",
            suggested_action="Wait for the run to pass ASSESSING_CHANGE_SAFETY before comparing.",
        )
    return run


@router.post("/repositories/{repo_id}/comparisons", response_model=ComparisonOut)
def create_comparison(
    repo_id: str, payload: ComparisonCreate, session: Session = Depends(get_session)
) -> ComparisonOut:
    if session.get(Repository, repo_id) is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"repository {repo_id!r} not found")
    if payload.base_run_id == payload.head_run_id:
        raise ArchonError(ErrorCode.CONFLICT, "base and head runs must differ")

    base_run = _load_run(session, repo_id, payload.base_run_id, "base")
    head_run = _load_run(session, repo_id, payload.head_run_id, "head")
    row = build_comparison(session, repo_id, base_run, head_run)
    return _full_out(row)


@router.get("/repositories/{repo_id}/comparisons", response_model=list[ComparisonSummaryOut])
def list_comparisons(
    repo_id: str, session: Session = Depends(get_session),
    limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
) -> list[ComparisonSummaryOut]:
    if session.get(Repository, repo_id) is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"repository {repo_id!r} not found")
    rows = session.scalars(
        select(RepositoryComparison)
        .where(RepositoryComparison.repo_id == repo_id)
        .order_by(RepositoryComparison.created_at.desc())
        .limit(limit).offset(offset)
    ).all()
    return [_summary_out(r) for r in rows]


@router.get("/comparisons/{comparison_id}", response_model=ComparisonOut)
def get_comparison(
    comparison_id: str, session: Session = Depends(get_session)
) -> ComparisonOut:
    row = session.get(RepositoryComparison, comparison_id)
    if row is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"comparison {comparison_id!r} not found")
    return _full_out(row)
