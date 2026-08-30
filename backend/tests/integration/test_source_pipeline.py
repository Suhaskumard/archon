"""ANALYZING_SOURCE stage through the real pipeline (spec sections 22, 53, 57)."""

from __future__ import annotations

from sqlalchemy import func, select

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    Component,
    Dependency,
    Job,
    Repository,
)
from archon.domain.enums import (
    ComponentKind,
    DependencyKind,
    JobState,
    RunMode,
    RunState,
    Stage,
)
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for


def _analysis_run(test_repo, mode=RunMode.ANALYSIS_ONLY) -> str:
    jobs = JobManager()
    with session_scope() as session:
        provider = provider_for(str(test_repo))
        ref = provider.parse(str(test_repo))
        repo = Repository(provider=provider.kind, url=ref.canonical_url, name=ref.name)
        session.add(repo)
        session.flush()
        job = jobs.create_run_with_job(session, repository_id=repo.id, mode=mode)
        run_id = job.run_id
    while Worker().tick():
        pass
    return run_id


def _kind_counts(session, sid: str) -> dict[str, int]:
    rows = session.execute(
        select(Component.kind, func.count(Component.id))
        .where(Component.snapshot_id == sid)
        .group_by(Component.kind)
    ).all()
    return {k.value: n for k, n in rows}


def _component(session, sid: str, qn: str, kind: ComponentKind) -> Component:
    return session.scalar(
        select(Component).where(
            Component.snapshot_id == sid,
            Component.qualified_name == qn,
            Component.kind == kind,
        )
    )


def test_source_stage_populates_components_and_dependencies(test_repo):
    run_id = _analysis_run(test_repo)
    with session_scope() as session:
        run = session.get(AnalysisRun, run_id)
        assert session.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is Stage.RECONSTRUCTING_ARCHITECTURE
        sid = run.snapshot_id

        kinds = _kind_counts(session, sid)
        assert kinds["MODULE"] == 8
        assert kinds["CLASS"] == 2
        assert kinds["METHOD"] == 4
        assert kinds["FUNCTION"] == 8

        billing = _component(session, sid, "legacy_shop.billing", ComponentKind.MODULE)
        calc = _component(session, sid, "legacy_shop.calculator", ComponentKind.MODULE)
        imports = session.scalars(
            select(Dependency).where(
                Dependency.snapshot_id == sid,
                Dependency.kind == DependencyKind.IMPORTS,
                Dependency.src_component_id == billing.id,
                Dependency.dst_component_id == calc.id,
            )
        ).all()
        assert len(imports) == 1 and imports[0].resolved

        inh = session.scalars(
            select(Dependency).where(
                Dependency.snapshot_id == sid, Dependency.kind == DependencyKind.INHERITS
            )
        ).all()
        assert len(inh) == 1 and inh[0].resolved

        contains = session.scalar(
            select(func.count(Dependency.id)).where(
                Dependency.snapshot_id == sid, Dependency.kind == DependencyKind.CONTAINS
            )
        )
        assert contains >= kinds["MODULE"] + kinds["CLASS"] + kinds["METHOD"]

        up = _component(session, sid, "legacy_shop.billing.unit_price", ComponentKind.FUNCTION)
        assert up.metrics["complexity"] == 2

        # a self-call inside a method resolves to the sibling method
        rush_total = _component(
            session, sid, "legacy_shop.orders.RushOrder.total", ComponentKind.METHOD
        )
        calls_from_rush = session.scalars(
            select(Dependency).where(
                Dependency.snapshot_id == sid,
                Dependency.kind == DependencyKind.CALLS,
                Dependency.src_component_id == rush_total.id,
            )
        ).all()
        # RushOrder.total calls super().total() (unresolvable) - no bogus edge emitted
        assert all(d.resolved for d in calls_from_rush)

        summaries = [e.summary for e in run.evidence]
        assert any("Extracted 8 Python modules" in s for s in summaries)
        assert any("Dependency edges" in s for s in summaries)


def test_source_analysis_is_cached_per_snapshot(test_repo):
    r1 = _analysis_run(test_repo)
    with session_scope() as session:
        run1 = session.get(AnalysisRun, r1)
        repo_id, sid1 = run1.repository_id, run1.snapshot_id
        n_components = session.scalar(
            select(func.count(Component.id)).where(Component.snapshot_id == sid1)
        )
        job = JobManager().create_run_with_job(
            session, repository_id=repo_id, mode=RunMode.ANALYSIS_ONLY, config_hash="v2"
        )
        r2 = job.run_id
    while Worker().tick():
        pass
    with session_scope() as session:
        r2run = session.get(AnalysisRun, r2)
        assert r2run.state is RunState.COMPLETED
        assert r2run.snapshot_id == sid1
        assert session.scalar(
            select(func.count(Component.id)).where(Component.snapshot_id == sid1)
        ) == n_components
        assert any("Reused cached source analysis" in e.summary for e in r2run.evidence)


def test_ingest_only_mode_skips_source(test_repo):
    run_id = _analysis_run(test_repo, mode=RunMode.INGEST_ONLY)
    with session_scope() as session:
        run = session.get(AnalysisRun, run_id)
        assert run.last_completed_stage is Stage.SNAPSHOTTING
        assert session.scalar(
            select(func.count(Component.id)).where(Component.snapshot_id == run.snapshot_id)
        ) == 0
