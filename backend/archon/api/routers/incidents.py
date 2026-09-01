"""Phase 10 incident memory endpoints (spec section 44, 47)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.api.deps import get_session
from archon.api.schemas import IncidentOut
from archon.core.errors import ArchonError, ErrorCode
from archon.db.models import AnalysisRun, Incident, Repository

router = APIRouter(tags=["incidents"])


def _incident_out(r: Incident) -> IncidentOut:
    return IncidentOut(
        id=r.id, run_id=r.run_id, repo_id=r.repo_id, failure_signature=r.failure_signature,
        failure_summary=r.failure_summary, root_cause=r.root_cause, evidence_ids=r.evidence_ids,
        affected_component_ids=r.affected_component_ids, fix_ref=r.fix_ref, patch_id=r.patch_id,
        regression_test_ids=r.regression_test_ids, verification_id=r.verification_id,
        confidence=r.confidence, created_at=r.created_at,
    )


@router.get("/runs/{run_id}/incidents", response_model=list[IncidentOut])
def list_run_incidents(
    run_id: str, session: Session = Depends(get_session),
    limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
) -> list[IncidentOut]:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"run {run_id!r} not found")
    rows = session.scalars(
        select(Incident).where(Incident.run_id == run_id).limit(limit).offset(offset)
    ).all()
    return [_incident_out(r) for r in rows]


@router.get("/repositories/{repo_id}/incidents", response_model=list[IncidentOut])
def list_repository_incidents(
    repo_id: str, session: Session = Depends(get_session),
    limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
) -> list[IncidentOut]:
    if session.get(Repository, repo_id) is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"repository {repo_id!r} not found")
    rows = session.scalars(
        select(Incident)
        .where(Incident.repo_id == repo_id)
        .order_by(Incident.created_at.desc())
        .limit(limit).offset(offset)
    ).all()
    return [_incident_out(r) for r in rows]
