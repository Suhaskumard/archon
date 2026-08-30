"""ANALYZING_GIT stage through the real pipeline (spec sections 24, 53)."""

from __future__ import annotations

from sqlalchemy import func, select

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    Commit,
    Component,
    Dependency,
    Job,
    Repository,
)
from archon.domain.enums import ComponentKind, DependencyKind, JobState, RunMode, RunState
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from tests.conftest import terminal_stage


def _full_run(test_repo) -> str:
    jobs = JobManager()
    with session_scope() as s:
        provider = provider_for(str(test_repo))
        ref = provider.parse(str(test_repo))
        repo = Repository(provider=provider.kind, url=ref.canonical_url, name=ref.name)
        s.add(repo)
        s.flush()
        rid = jobs.create_run_with_job(s, repository_id=repo.id, mode=RunMode.FULL).run_id
    w = Worker()
    while w.tick():
        pass
    return rid


def _module(s, sid, qn):
    return s.scalar(
        select(Component).where(
            Component.snapshot_id == sid,
            Component.qualified_name == qn,
            Component.kind == ComponentKind.MODULE,
        )
    )


def test_git_stage_populates_commits_metrics_and_edges(test_repo):
    rid = _full_run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is terminal_stage("FULL")
        sid = run.snapshot_id

        assert s.scalar(select(func.count(Commit.id)).where(Commit.snapshot_id == sid)) == 3

        billing = _module(s, sid, "legacy_shop.billing")
        calc = _module(s, sid, "legacy_shop.calculator")
        inv = _module(s, sid, "legacy_shop.inventory")
        assert billing.metrics["git"]["commit_count"] == 2
        assert calc.metrics["git"]["commit_count"] == 1
        # billing / calculator (commit 1) are older than inventory (commit 2)
        assert billing.metrics["git"]["age_days"] > inv.metrics["git"]["age_days"]
        assert billing.metrics["git"]["churn"] > 0

        # CHANGED_WITH: billing <-> calculator (both in the initial commit)
        cw = s.scalar(
            select(func.count(Dependency.id)).where(
                Dependency.snapshot_id == sid,
                Dependency.kind == DependencyKind.CHANGED_WITH,
                Dependency.src_component_id == billing.id,
                Dependency.dst_component_id == calc.id,
            )
        )
        assert cw == 1
        # no config/__init__ noise: every CHANGED_WITH endpoint is a MODULE
        all_cw = s.scalars(
            select(Dependency).where(
                Dependency.snapshot_id == sid, Dependency.kind == DependencyKind.CHANGED_WITH
            )
        ).all()
        mod_ids = {
            c.id for c in s.scalars(
                select(Component).where(
                    Component.snapshot_id == sid, Component.kind == ComponentKind.MODULE
                )
            ).all()
        }
        assert all(e.src_component_id in mod_ids and e.dst_component_id in mod_ids for e in all_cw)

        # CHANGED_BY on billing points at its commits
        cb = s.scalars(
            select(Dependency).where(
                Dependency.snapshot_id == sid,
                Dependency.kind == DependencyKind.CHANGED_BY,
                Dependency.src_component_id == billing.id,
            )
        ).all()
        assert len(cb) == 2 and all(d.dst_component_id is None for d in cb)
        assert all(d.attributes.get("commit_id") for d in cb)

        assert any("Analyzed 3 commit(s)" in e.summary for e in run.evidence)
        assert run.engine_versions.get("git") == "git.v1"


def test_git_analysis_cached_per_snapshot(test_repo):
    r1 = _full_run(test_repo)
    with session_scope() as s:
        run1 = s.get(AnalysisRun, r1)
        sid = run1.snapshot_id
        n_commits = s.scalar(select(func.count(Commit.id)).where(Commit.snapshot_id == sid))
        job = JobManager().create_run_with_job(
            s, repository_id=run1.repository_id, mode=RunMode.FULL, config_hash="v2"
        )
        r2 = job.run_id
    w = Worker()
    while w.tick():
        pass
    with session_scope() as s:
        r2run = s.get(AnalysisRun, r2)
        assert r2run.snapshot_id == sid
        assert s.scalar(select(func.count(Commit.id)).where(Commit.snapshot_id == sid)) == n_commits
        assert any("Reused cached git analysis" in e.summary for e in r2run.evidence)
