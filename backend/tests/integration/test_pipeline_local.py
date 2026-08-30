"""Phase 1 pipeline end-to-end against a real local git repo (spec sections 20-21, 57)."""

from __future__ import annotations

from archon.db.base import session_scope
from archon.db.models import AnalysisRun, Job, Repository, RepositorySnapshot
from archon.domain.enums import Classification, JobState, RunMode, RunState, Stage
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for


def _make_repo(session, path) -> Repository:
    provider = provider_for(str(path))
    ref = provider.parse(str(path))
    repo = Repository(provider=provider.kind, url=ref.canonical_url, name=ref.name)
    session.add(repo)
    session.flush()
    return repo


def test_worker_ingests_local_repo(test_repo):
    jobs = JobManager()
    with session_scope() as session:
        repo = _make_repo(session, test_repo)
        job = jobs.create_run_with_job(session, repository_id=repo.id, mode=RunMode.INGEST_ONLY)
        run_id, job_id = job.run_id, job.id

    assert Worker().tick() is True

    with session_scope() as session:
        run = session.get(AnalysisRun, run_id)
        job = session.get(Job, job_id)
        snap = session.get(RepositorySnapshot, run.snapshot_id)

        assert job.state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is Stage.SNAPSHOTTING
        assert run.progress_pct == 100.0

        assert snap is not None
        assert len(snap.commit_sha) == 40
        assert snap.commit_count == 3
        assert snap.file_count > 0
        assert snap.support_level.value == "SUPPORTED"

        classifications = {e.classification for e in run.evidence}
        assert Classification.FACT in classifications
        assert any("Cloned" in e.summary for e in run.evidence)


def test_snapshot_is_reused_for_same_commit(test_repo):
    jobs = JobManager()
    with session_scope() as session:
        repo = _make_repo(session, test_repo)
        j1 = jobs.create_run_with_job(
            session, repository_id=repo.id, config_hash="a", mode=RunMode.INGEST_ONLY
        )
        run1 = j1.run_id
    Worker().tick()

    with session_scope() as session:
        repo_id = session.get(AnalysisRun, run1).repository_id
        j2 = jobs.create_run_with_job(
            session, repository_id=repo_id, config_hash="b", mode=RunMode.INGEST_ONLY
        )
        run2 = j2.run_id
    Worker().tick()

    with session_scope() as session:
        s1 = session.get(AnalysisRun, run1).snapshot_id
        s2 = session.get(AnalysisRun, run2).snapshot_id
        assert s1 == s2
        assert session.query(RepositorySnapshot).count() == 1


def test_ref_checkout(test_repo):
    """Requesting the first commit yields a snapshot pinned to it."""
    from archon.providers.repo.gitcli import run_git

    first = run_git(["rev-list", "--max-parents=0", "HEAD"], cwd=test_repo).stdout.strip()
    jobs = JobManager()
    with session_scope() as session:
        repo = _make_repo(session, test_repo)
        job = jobs.create_run_with_job(
            session, repository_id=repo.id, requested_ref=first, mode=RunMode.INGEST_ONLY
        )
        run_id = job.run_id
    Worker().tick()
    with session_scope() as session:
        run = session.get(AnalysisRun, run_id)
        snap = session.get(RepositorySnapshot, run.snapshot_id)
        assert snap.commit_sha == first
        assert snap.commit_count == 1


def test_cancelled_run_is_reported(test_repo, monkeypatch):
    jobs = JobManager()
    with session_scope() as session:
        repo = _make_repo(session, test_repo)
        job = jobs.create_run_with_job(session, repository_id=repo.id, mode=RunMode.INGEST_ONLY)
        run_id, job_id = job.run_id, job.id

    # request cancellation before the worker picks it up
    with session_scope() as session:
        jobs.request_cancel(session, run_id)

    Worker().tick()
    with session_scope() as session:
        assert session.get(Job, job_id).state is JobState.CANCELLED
        assert session.get(AnalysisRun, run_id).state is RunState.CANCELLED
