"""Software-archaeology endpoints: git evolution, behaviour, hidden assumptions
(spec sections 24-26, 47)."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archon.api.deps import get_session
from archon.api.schemas import (
    AssumptionOut,
    BehaviorOut,
    CommitOut,
    ComponentHistoryOut,
    EvolutionOut,
)
from archon.core.errors import ArchonError, ErrorCode
from archon.db.models import (
    AnalysisRun,
    Assumption,
    BehaviorReconstruction,
    Commit,
    Component,
    Dependency,
    RepositorySnapshot,
)
from archon.domain.enums import DependencyKind

router = APIRouter(tags=["archaeology"])


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


def _commit_out(c: Commit) -> CommitOut:
    return CommitOut(
        id=c.id, sha=c.sha, author_name=c.author_name, author_email=c.author_email,
        authored_at=c.authored_at, message=c.message, files_changed=c.files_changed,
        insertions=c.insertions, deletions=c.deletions, is_merge=c.is_merge,
        changed_paths=c.changed_paths,
    )


@router.get("/snapshots/{snapshot_id}/commits", response_model=list[CommitOut])
def list_commits(
    snapshot_id: str,
    session: Session = Depends(get_session),
    author: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[CommitOut]:
    if session.get(RepositorySnapshot, snapshot_id) is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"snapshot {snapshot_id!r} not found")
    stmt = select(Commit).where(Commit.snapshot_id == snapshot_id)
    if author:
        stmt = stmt.where(
            (Commit.author_email.contains(author)) | (Commit.author_name.contains(author))
        )
    stmt = stmt.order_by(Commit.authored_at.desc()).limit(limit).offset(offset)
    return [_commit_out(c) for c in session.scalars(stmt).all()]


@router.get("/runs/{run_id}/evolution", response_model=EvolutionOut)
def get_evolution(run_id: str, session: Session = Depends(get_session)) -> EvolutionOut:
    run = _run_with_snapshot(session, run_id)
    sid = run.snapshot_id
    commits = session.scalars(
        select(Commit).where(Commit.snapshot_id == sid).order_by(Commit.authored_at)
    ).all()
    if not commits:
        raise ArchonError(
            ErrorCode.CONFLICT, "git analysis has not run for this run",
            suggested_action="Run the analysis in ANALYSIS_ONLY or FULL mode.",
        )

    authors = {c.author_email for c in commits if c.author_email}
    dated = [c for c in commits if c.authored_at]
    span_days = (
        (max(c.authored_at for c in dated) - min(c.authored_at for c in dated)).days
        if dated else 0
    )

    timeline_map: dict[str, dict] = defaultdict(lambda: {"commits": 0, "churn": 0})
    for c in commits:
        key = c.authored_at.strftime("%Y-%m") if c.authored_at else "unknown"
        timeline_map[key]["commits"] += 1
        timeline_map[key]["churn"] += c.insertions + c.deletions
    timeline = [{"month": k, **v} for k, v in sorted(timeline_map.items())]

    # top churn from module components
    mods = session.scalars(
        select(Component).where(
            Component.snapshot_id == sid, Component.kind == "MODULE"
        )
    ).all()
    top_churn = sorted(
        (
            {"path": m.path, "qualified_name": m.qualified_name,
             **{k: (m.metrics or {}).get("git", {}).get(k, 0)
                for k in ("churn", "commit_count", "age_days")}}
            for m in mods
            if (m.metrics or {}).get("git")
        ),
        key=lambda d: d["churn"],
        reverse=True,
    )[:10]

    # top co-change from CHANGED_WITH edges (dedupe direction)
    seen: set[frozenset] = set()
    co: list[dict] = []
    edges = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == sid,
            Dependency.kind == DependencyKind.CHANGED_WITH,
        )
    ).all()
    id_to_qn = {
        c.id: c.qualified_name
        for c in session.scalars(select(Component).where(Component.snapshot_id == sid)).all()
    }
    for e in edges:
        pair = frozenset({e.src_component_id, e.dst_component_id})
        if pair in seen:
            continue
        seen.add(pair)
        co.append({
            "a": id_to_qn.get(e.src_component_id),
            "b": id_to_qn.get(e.dst_component_id),
            "count": (e.attributes or {}).get("count", 0),
            "confidence": (e.attributes or {}).get("confidence", 0.0),
        })
    co.sort(key=lambda d: (d["count"], d["confidence"]), reverse=True)

    return EvolutionOut(
        run_id=run_id, snapshot_id=sid,
        total_commits=len(commits), analyzed_commits=len(commits),
        span_days=span_days, authors=len(authors), truncated=False,
        timeline=timeline, top_churn=top_churn, top_co_change=co[:10],
    )


@router.get("/components/{component_id}/history", response_model=ComponentHistoryOut)
def component_history(
    component_id: str, session: Session = Depends(get_session)
) -> ComponentHistoryOut:
    comp = session.get(Component, component_id)
    if comp is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"component {component_id!r} not found")
    sid = comp.snapshot_id

    changed_by = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == sid,
            Dependency.src_component_id == component_id,
            Dependency.kind == DependencyKind.CHANGED_BY,
        )
    ).all()
    commit_ids = [
        (d.attributes or {}).get("commit_id") for d in changed_by if (d.attributes or {}).get("commit_id")
    ]
    commits = session.scalars(
        select(Commit).where(Commit.id.in_(commit_ids)).order_by(Commit.authored_at.desc())
    ).all()

    changed_with = session.scalars(
        select(Dependency).where(
            Dependency.snapshot_id == sid,
            Dependency.src_component_id == component_id,
            Dependency.kind == DependencyKind.CHANGED_WITH,
        )
    ).all()
    neighbours = [
        {
            "qualified_name": d.target_name,
            "count": (d.attributes or {}).get("count", 0),
            "confidence": (d.attributes or {}).get("confidence", 0.0),
        }
        for d in changed_with
    ]
    neighbours.sort(key=lambda d: (d["count"], d["confidence"]), reverse=True)

    return ComponentHistoryOut(
        component_id=comp.id,
        qualified_name=comp.qualified_name,
        path=comp.path,
        git=(comp.metrics or {}).get("git", {}),
        commits=[_commit_out(c) for c in commits],
        co_changed_with=neighbours,
    )


# --- behaviour / assumptions ------------------------------------------------------


def _behavior_out(b: BehaviorReconstruction, qn: str | None) -> BehaviorOut:
    return BehaviorOut(
        id=b.id, component_id=b.component_id, component_qn=qn,
        purpose=b.purpose, historical_context=b.historical_context,
        current_role=b.current_role, inputs=b.inputs, outputs=b.outputs,
        side_effects=b.side_effects, exceptions=b.exceptions, callers=b.callers,
        callees=b.callees, tests=b.tests, likely_invariants=b.likely_invariants,
        git=b.git, classification=b.classification, confidence=b.confidence,
        produced_by=b.produced_by,
    )


@router.get("/runs/{run_id}/behavior", response_model=list[BehaviorOut])
def list_behavior(
    run_id: str,
    session: Session = Depends(get_session),
    q: str | None = Query(default=None, description="substring on component qualified_name"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[BehaviorOut]:
    _run_with_snapshot(session, run_id)
    rows = session.scalars(
        select(BehaviorReconstruction).where(BehaviorReconstruction.run_id == run_id)
    ).all()
    qn_map = {
        c.id: c.qualified_name
        for c in session.scalars(
            select(Component).where(Component.id.in_([r.component_id for r in rows]))
        ).all()
    }
    out = [_behavior_out(r, qn_map.get(r.component_id)) for r in rows]
    if q:
        out = [b for b in out if b.component_qn and q in b.component_qn]
    out.sort(key=lambda b: b.component_qn or "")
    return out[offset : offset + limit]


@router.get("/components/{component_id}/behavior", response_model=BehaviorOut | None)
def component_behavior(
    component_id: str,
    session: Session = Depends(get_session),
    run_id: str | None = Query(default=None),
) -> BehaviorOut | None:
    comp = session.get(Component, component_id)
    if comp is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"component {component_id!r} not found")
    stmt = select(BehaviorReconstruction).where(
        BehaviorReconstruction.component_id == component_id
    )
    if run_id:
        stmt = stmt.where(BehaviorReconstruction.run_id == run_id)
    row = session.scalars(stmt.order_by(BehaviorReconstruction.created_at.desc())).first()
    return _behavior_out(row, comp.qualified_name) if row else None


@router.get("/runs/{run_id}/assumptions", response_model=list[AssumptionOut])
def list_assumptions(
    run_id: str,
    session: Session = Depends(get_session),
    kind: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> list[AssumptionOut]:
    _run_with_snapshot(session, run_id)
    stmt = select(Assumption).where(Assumption.run_id == run_id)
    if kind:
        stmt = stmt.where(Assumption.kind == kind)
    if risk:
        stmt = stmt.where(Assumption.risk == risk.upper())
    if component_id:
        stmt = stmt.where(Assumption.component_id == component_id)
    rows = session.scalars(stmt.limit(limit).offset(offset)).all()
    qn_map = {
        c.id: c.qualified_name
        for c in session.scalars(
            select(Component).where(
                Component.id.in_([r.component_id for r in rows if r.component_id])
            )
        ).all()
    }
    risk_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    out = [
        AssumptionOut(
            id=r.id, kind=r.kind, description=r.description, location=r.location,
            risk=r.risk, confidence=r.confidence, suggested_test=r.suggested_test,
            component_id=r.component_id, component_qn=qn_map.get(r.component_id),
            produced_by=r.produced_by, detail=r.detail, created_at=r.created_at,
        )
        for r in rows
    ]
    out.sort(key=lambda a: (risk_rank.get(a.risk or "LOW", 3), a.kind))
    return out


def _run_assumption_count(session: Session, run_id: str) -> int:
    return int(
        session.scalar(
            select(func.count(Assumption.id)).where(Assumption.run_id == run_id)
        )
        or 0
    )
