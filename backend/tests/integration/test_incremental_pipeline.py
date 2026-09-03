"""RunMode.INCREMENTAL through the worker - scoped change-impact + no dedupe across shas."""

from __future__ import annotations

from archon.db.base import session_scope
from archon.db.models import AnalysisRun, ChangeImpact, Job, Repository
from archon.domain.enums import JobState, RunMode, RunState, Stage
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from tests.conftest import terminal_stage


def _make_repo(session, path) -> Repository:
    provider = provider_for(str(path))
    ref = provider.parse(str(path))
    repo = Repository(provider=provider.kind, url=ref.canonical_url, name=ref.name)
    session.add(repo)
    session.flush()
    return repo


def _run(session, jobs, repo_id, *, mode, changed_paths=None, sha):
    # ``sha`` only varies the dedupe/config hash here - the fixture repo is checked out at
    # its default branch (requested_ref=None).
    job = jobs.create_run_with_job(
        session, repository_id=repo_id, mode=mode, requested_ref=None,
        config_hash=f"h-{sha}", changed_paths=changed_paths,
    )
    return job.run_id, job.id


def test_incremental_completes_sandbox_free_and_scopes_change_impact(test_repo):
    jobs = JobManager()
    with session_scope() as session:
        repo = _make_repo(session, test_repo)
        inc_id, inc_job = _run(
            session, jobs, repo.id, mode=RunMode.INCREMENTAL,
            changed_paths=["legacy_shop/calculator.py"], sha="sha-1",
        )

    w = Worker()
    for _ in range(20):
        if not w.tick():
            break

    with session_scope() as session:
        run = session.get(AnalysisRun, inc_id)
        job = session.get(Job, inc_job)
        assert job.state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is Stage.ANALYZING_TESTS
        assert run.last_completed_stage is terminal_stage("INCREMENTAL")

        impact_rows = session.query(ChangeImpact).filter_by(run_id=inc_id).all()
        # scoped: at most the module(s) owning the one changed file, not every module
        assert 0 < len(impact_rows) <= 2

        # an incremental run makes no AI calls -> no claude evidence, archaeology skipped
        produced = {e.produced_by for e in run.evidence}
        assert "incremental.v1" in produced
        assert not any(p.startswith("claude:") for p in produced)


def test_second_push_for_a_different_sha_is_not_dedupe_blocked(test_repo):
    jobs = JobManager()
    with session_scope() as session:
        repo = _make_repo(session, test_repo)
        _run(session, jobs, repo.id, mode=RunMode.INCREMENTAL,
             changed_paths=["legacy_shop/calculator.py"], sha="sha-a")
    with session_scope() as session:
        repo = session.query(Repository).one()
        # different sha -> different config_hash -> no CONFLICT
        _run(session, jobs, repo.id, mode=RunMode.INCREMENTAL,
             changed_paths=["legacy_shop/billing.py"], sha="sha-b")

    with session_scope() as session:
        assert session.query(AnalysisRun).filter_by(mode=RunMode.INCREMENTAL).count() == 2
