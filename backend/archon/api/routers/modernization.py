"""Phase 12 modernization endpoint (spec sections 46, 47).

Read-only: the ``MODERNIZING`` pipeline stage produces the plan; this exposes it,
ordered safest-first, with each row's confidence + classification.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.api.deps import get_session
from archon.api.schemas import ModernizationRecommendationOut
from archon.core.errors import ArchonError, ErrorCode
from archon.db.models import AnalysisRun, Component, ModernizationRecommendation

router = APIRouter(tags=["modernization"])


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


def _qn_map(session: Session, ids: list[str | None]) -> dict[str, str]:
    real = [i for i in ids if i]
    if not real:
        return {}
    return {
        c.id: c.qualified_name
        for c in session.scalars(select(Component).where(Component.id.in_(real))).all()
    }


def _out(r: ModernizationRecommendation, qn: str | None) -> ModernizationRecommendationOut:
    return ModernizationRecommendationOut(
        id=r.id, run_id=r.run_id, target=r.target, component_id=r.component_id,
        component_qn=qn,
        strategy=r.strategy.value if hasattr(r.strategy, "value") else str(r.strategy),
        risk=r.risk, effort=r.effort, impact=r.impact, order_index=r.order_index,
        rationale=r.rationale, dependencies=r.dependencies, required_tests=r.required_tests,
        prerequisites=r.prerequisites, change_safety_ref=r.change_safety_ref,
        confidence=r.confidence, classification=r.classification,
        ai_schema_version=r.ai_schema_version, evidence_ids=r.evidence_ids,
        created_at=r.created_at,
    )


@router.get("/runs/{run_id}/modernization", response_model=list[ModernizationRecommendationOut])
def list_modernization(
    run_id: str,
    session: Session = Depends(get_session),
    strategy: str | None = Query(default=None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> list[ModernizationRecommendationOut]:
    _run_with_snapshot(session, run_id)
    stmt = select(ModernizationRecommendation).where(ModernizationRecommendation.run_id == run_id)
    if strategy:
        stmt = stmt.where(ModernizationRecommendation.strategy == strategy.upper())
    rows = session.scalars(
        stmt.order_by(ModernizationRecommendation.order_index).limit(limit).offset(offset)
    ).all()
    qn = _qn_map(session, [r.component_id for r in rows])
    return [_out(r, qn.get(r.component_id)) for r in rows]
