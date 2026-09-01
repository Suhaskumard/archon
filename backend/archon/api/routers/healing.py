"""Phase 9 failure investigation & self-healing endpoints: failures, investigations,
patches, verifications (spec sections 37-43, 47)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.api.deps import get_session
from archon.api.schemas import FailureOut, InvestigationOut, PatchOut, PatchVerificationOut
from archon.core.artifacts import read_text
from archon.core.errors import ArchonError, ErrorCode
from archon.db.models import (
    AnalysisArtifact,
    AnalysisRun,
    Failure,
    Investigation,
    Patch,
    PatchVerification,
)

router = APIRouter(tags=["healing"])

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
    return read_text(art)[-_PREVIEW_CHARS:]


@router.get("/runs/{run_id}/failures", response_model=list[FailureOut])
def list_failures(
    run_id: str, session: Session = Depends(get_session),
    limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
) -> list[FailureOut]:
    _run_with_snapshot(session, run_id)
    rows = session.scalars(
        select(Failure).where(Failure.run_id == run_id).limit(limit).offset(offset)
    ).all()
    return [
        FailureOut(
            id=r.id, execution_id=r.execution_id, test_identifier=r.test_identifier,
            message=r.message, exception_type=r.exception_type, stack_trace_ref=r.stack_trace_ref,
            parsed_frames=r.parsed_frames, reproducible=r.reproducible, occurrences=r.occurrences,
            first_seen=r.first_seen,
        )
        for r in rows
    ]


@router.get("/runs/{run_id}/investigations", response_model=list[InvestigationOut])
def list_investigations(
    run_id: str, session: Session = Depends(get_session),
    limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
) -> list[InvestigationOut]:
    _run_with_snapshot(session, run_id)
    rows = session.scalars(
        select(Investigation).where(Investigation.run_id == run_id).limit(limit).offset(offset)
    ).all()
    return [
        InvestigationOut(
            id=r.id, failure_id=r.failure_id, summary=r.summary,
            root_cause_hypotheses=r.root_cause_hypotheses,
            affected_component_ids=r.affected_component_ids,
            recommended_verification=r.recommended_verification,
            confidence=r.confidence, ai_schema_version=r.ai_schema_version,
            cited_incident_ids=r.cited_incident_ids,
        )
        for r in rows
    ]


@router.get("/runs/{run_id}/patches", response_model=list[PatchOut])
def list_patches(
    run_id: str, session: Session = Depends(get_session),
    state: str | None = Query(default=None),
    limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
) -> list[PatchOut]:
    _run_with_snapshot(session, run_id)
    stmt = select(Patch).where(Patch.run_id == run_id)
    if state:
        stmt = stmt.where(Patch.state == state.upper())
    rows = session.scalars(
        stmt.order_by(Patch.rank_score.desc()).limit(limit).offset(offset)
    ).all()
    return [
        PatchOut(
            id=r.id, investigation_id=r.investigation_id, strategy=r.strategy,
            diff_preview=_preview(session, r.diff_ref), diff_ref=r.diff_ref,
            target_component_ids=r.target_component_ids, lines_added=r.lines_added,
            lines_removed=r.lines_removed, static_validation=r.static_validation,
            rank_score=r.rank_score, rank_breakdown=r.rank_breakdown,
            state=r.state.value if hasattr(r.state, "value") else r.state,
            ai_schema_version=r.ai_schema_version,
        )
        for r in rows
    ]


@router.get("/runs/{run_id}/verifications", response_model=list[PatchVerificationOut])
def list_verifications(
    run_id: str, session: Session = Depends(get_session),
    limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
) -> list[PatchVerificationOut]:
    _run_with_snapshot(session, run_id)
    rows = session.scalars(
        select(PatchVerification).where(PatchVerification.run_id == run_id).limit(limit).offset(offset)
    ).all()
    return [
        PatchVerificationOut(
            id=r.id, patch_id=r.patch_id, original_failure_fixed=r.original_failure_fixed,
            characterization_pass=r.characterization_pass, regression_pass=r.regression_pass,
            existing_tests_pass=r.existing_tests_pass, new_critical_failures=r.new_critical_failures,
            applies_cleanly=r.applies_cleanly,
            verdict=r.verdict.value if hasattr(r.verdict, "value") else r.verdict,
            execution_ids=r.execution_ids,
        )
        for r in rows
    ]
