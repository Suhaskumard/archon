"""Phase 5 scoring endpoints: legacy DNA, hotspots, technical debt, understanding
(spec sections 27-30, 47)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.api.deps import get_session
from archon.api.schemas import (
    HotspotOut,
    LegacyDnaOut,
    RepositoryUnderstandingOut,
    TechnicalDebtFindingOut,
    UnderstandingDimensionOut,
)
from archon.core.artifacts import read_json
from archon.core.errors import ArchonError, ErrorCode
from archon.db.models import (
    AnalysisArtifact,
    AnalysisRun,
    Component,
    Hotspot,
    LegacyDNA,
    TechnicalDebtFinding,
)

router = APIRouter(tags=["scoring"])


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


def _qn_map(session: Session, component_ids: list[str | None]) -> dict[str, str]:
    ids = [c for c in component_ids if c]
    if not ids:
        return {}
    return {
        c.id: c.qualified_name
        for c in session.scalars(select(Component).where(Component.id.in_(ids))).all()
    }


# --- Legacy DNA ----------------------------------------------------------------------


def _legacy_dna_out(r: LegacyDNA, qn: str | None) -> LegacyDnaOut:
    return LegacyDnaOut(
        id=r.id, component_id=r.component_id, component_qn=qn,
        age_days=r.age_days, complexity=r.complexity, churn=r.churn, coupling=r.coupling,
        coverage=r.coverage, coverage_is_proxy=r.coverage_is_proxy,
        failure_count=r.failure_count, assumption_count=r.assumption_count,
        debt_score=r.debt_score, legacy_risk_score=r.legacy_risk_score,
        category=r.category.value if hasattr(r.category, "value") else r.category,
        confidence=r.confidence, factor_breakdown=r.factor_breakdown,
    )


@router.get("/runs/{run_id}/legacy-dna", response_model=list[LegacyDnaOut])
def list_legacy_dna(
    run_id: str,
    session: Session = Depends(get_session),
    category: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> list[LegacyDnaOut]:
    _run_with_snapshot(session, run_id)
    stmt = select(LegacyDNA).where(LegacyDNA.run_id == run_id)
    if category:
        stmt = stmt.where(LegacyDNA.category == category.upper())
    if component_id:
        stmt = stmt.where(LegacyDNA.component_id == component_id)
    rows = session.scalars(
        stmt.order_by(LegacyDNA.legacy_risk_score.desc()).limit(limit).offset(offset)
    ).all()
    qn_map = _qn_map(session, [r.component_id for r in rows])
    return [_legacy_dna_out(r, qn_map.get(r.component_id)) for r in rows]


@router.get("/components/{component_id}/legacy-dna", response_model=LegacyDnaOut | None)
def component_legacy_dna(
    component_id: str,
    session: Session = Depends(get_session),
    run_id: str | None = Query(default=None),
) -> LegacyDnaOut | None:
    comp = session.get(Component, component_id)
    if comp is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"component {component_id!r} not found")
    stmt = select(LegacyDNA).where(LegacyDNA.component_id == component_id)
    if run_id:
        stmt = stmt.where(LegacyDNA.run_id == run_id)
    row = session.scalars(stmt.order_by(LegacyDNA.created_at.desc())).first()
    return _legacy_dna_out(row, comp.qualified_name) if row else None


# --- Hotspots --------------------------------------------------------------------------


@router.get("/runs/{run_id}/hotspots", response_model=list[HotspotOut])
def list_hotspots(
    run_id: str,
    session: Session = Depends(get_session),
    classification: str | None = Query(default=None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> list[HotspotOut]:
    _run_with_snapshot(session, run_id)
    stmt = select(Hotspot).where(Hotspot.run_id == run_id)
    if classification:
        stmt = stmt.where(Hotspot.classification == classification.upper())
    rows = session.scalars(
        stmt.order_by(Hotspot.score.desc()).limit(limit).offset(offset)
    ).all()
    qn_map = _qn_map(session, [r.component_id for r in rows])
    return [
        HotspotOut(
            id=r.id, component_id=r.component_id, component_qn=qn_map.get(r.component_id),
            score=r.score,
            classification=r.classification.value if hasattr(r.classification, "value") else r.classification,
            reasons=r.reasons,
        )
        for r in rows
    ]


# --- Technical debt ----------------------------------------------------------------


@router.get("/runs/{run_id}/technical-debt", response_model=list[TechnicalDebtFindingOut])
def list_technical_debt(
    run_id: str,
    session: Session = Depends(get_session),
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> list[TechnicalDebtFindingOut]:
    _run_with_snapshot(session, run_id)
    stmt = select(TechnicalDebtFinding).where(TechnicalDebtFinding.run_id == run_id)
    if category:
        stmt = stmt.where(TechnicalDebtFinding.category == category.upper())
    if severity:
        stmt = stmt.where(TechnicalDebtFinding.severity == severity.upper())
    if component_id:
        stmt = stmt.where(TechnicalDebtFinding.component_id == component_id)
    rows = session.scalars(stmt.limit(limit).offset(offset)).all()
    qn_map = _qn_map(session, [r.component_id for r in rows])
    severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    out = [
        TechnicalDebtFindingOut(
            id=r.id, component_id=r.component_id, component_qn=qn_map.get(r.component_id),
            category=r.category.value if hasattr(r.category, "value") else r.category,
            location=r.location, evidence=r.evidence,
            severity=r.severity.value if hasattr(r.severity, "value") else r.severity,
            impact=r.impact, confidence=r.confidence, recommendation=r.recommendation,
        )
        for r in rows
    ]
    out.sort(key=lambda f: severity_rank.get(f.severity, 4))
    return out


# --- Repository understanding -------------------------------------------------------


@router.get("/runs/{run_id}/understanding", response_model=RepositoryUnderstandingOut)
def get_understanding(run_id: str, session: Session = Depends(get_session)) -> RepositoryUnderstandingOut:
    run = _run_with_snapshot(session, run_id)
    artifact = session.scalar(
        select(AnalysisArtifact).where(
            AnalysisArtifact.run_id == run_id, AnalysisArtifact.kind == "understanding"
        )
    )
    if artifact is None:
        raise ArchonError(
            ErrorCode.CONFLICT, "repository understanding has not been scored for this run",
            suggested_action="Run the analysis in ANALYSIS_ONLY or FULL mode.",
        )
    data = read_json(artifact)
    return RepositoryUnderstandingOut(
        run_id=run_id, snapshot_id=run.snapshot_id,
        overall_score=data["score"], confidence=data["confidence"],
        dimensions=[
            UnderstandingDimensionOut(name=name, score=round(value * 100.0, 2))
            for name, value in data["dimensions"].items()
        ],
        evidence_coverage=data["evidence_coverage"],
    )
