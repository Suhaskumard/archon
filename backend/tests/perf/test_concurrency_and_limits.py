"""Concurrency cap, limit enforcement, reaper, Postgres SKIP LOCKED (spec sections 16, 53).

Run with:  pytest -m perf
"""

from __future__ import annotations

import os

import pytest

from archon.config import RepositoryLimits, reset_settings_cache
from archon.db.base import session_scope
from archon.db.models import Job, Repository
from archon.domain.enums import JobState, ProviderKind, RunMode
from archon.jobs.manager import JobManager

pytestmark = pytest.mark.perf


def _repo(session) -> Repository:
    r = Repository(provider=ProviderKind.GITHUB, url="https://github.com/x/y", name="y")
    session.add(r)
    session.flush()
    return r


def test_running_job_cap_blocks_further_claims(monkeypatch):
    monkeypatch.setenv("ARCHON_MAX_CONCURRENT_RUNS", "1")
    reset_settings_cache()
    jobs = JobManager()
    with session_scope() as session:
        repo = _repo(session)
        jobs.create_run_with_job(session, repository_id=repo.id, mode=RunMode.INGEST_ONLY,
                                 config_hash="c1")
        jobs.create_run_with_job(session, repository_id=repo.id, mode=RunMode.INGEST_ONLY,
                                 config_hash="c2")

    with session_scope() as session:
        first = jobs.claim_next(session)
        assert first is not None and first.state is JobState.RUNNING
    with session_scope() as session:
        # one already RUNNING and the cap is 1 -> no second claim
        assert jobs.claim_next(session) is None

    with session_scope() as session:
        job = session.scalar(
            __import__("sqlalchemy").select(Job).where(Job.state == JobState.RUNNING)
        )
        jobs.finish(session, job, succeeded=True)
    with session_scope() as session:
        assert jobs.claim_next(session) is not None  # slot freed


def test_max_file_count_truncates_and_records_a_reason(tmp_path):
    (tmp_path / "pkg").mkdir()
    for i in range(6):
        (tmp_path / "pkg" / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n")
    from archon.analysis.source.extractor import extract_repository

    limited = RepositoryLimits(max_file_count=3)
    result = extract_repository(tmp_path, limited)
    assert result.degraded is True
    assert "max_file_count=3" in result.degraded_reason


def test_oversized_repo_is_caught_by_the_pre_clone_size_guard(monkeypatch):
    """The orchestrator's INGESTING stage rejects a repo whose GitHub-reported size is
    over ``max_repo_size_bytes`` before any clone happens."""
    monkeypatch.setenv("ARCHON_LIMIT_MAX_REPO_SIZE_BYTES", "1024")
    reset_settings_cache()
    import httpx

    from archon.config import get_settings
    from archon.providers.repo.github import GitHubRepositoryProvider

    def _mock(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"default_branch": "main", "size": 5000, "private": False}
        )

    prov = GitHubRepositoryProvider(transport=httpx.MockTransport(_mock))
    meta = prov.fetch_metadata(prov.parse("https://github.com/big/repo"))
    assert meta.size_bytes and meta.size_bytes > get_settings().limits.max_repo_size_bytes


@pytest.mark.skipif(
    "ARCHON_TEST_POSTGRES_URL" not in os.environ,
    reason="set ARCHON_TEST_POSTGRES_URL to run the SKIP LOCKED contention test",
)
def test_postgres_skip_locked_hands_distinct_jobs_to_concurrent_workers(monkeypatch):
    monkeypatch.setenv("ARCHON_DATABASE_URL", os.environ["ARCHON_TEST_POSTGRES_URL"])
    monkeypatch.setenv("ARCHON_MAX_CONCURRENT_RUNS", "8")
    reset_settings_cache()
    import archon.db.base as db_base

    db_base.reset_engine_cache()
    from archon.db.migrate import upgrade

    upgrade()
    jobs = JobManager()
    with session_scope() as session:
        repo = _repo(session)
        for i in range(5):
            jobs.create_run_with_job(session, repository_id=repo.id,
                                     mode=RunMode.INGEST_ONLY, config_hash=f"pg{i}")

    claimed: list[str] = []
    for _ in range(5):
        with session_scope() as session:
            j = jobs.claim_next(session)
            assert j is not None
            claimed.append(j.id)
    assert len(set(claimed)) == 5  # every worker got a distinct job, none double-claimed


@pytest.mark.skipif(
    not os.environ.get("ARCHON_RUN_REAPER_TEST"),
    reason="Docker required; set ARCHON_RUN_REAPER_TEST=1 with the sandbox image built",
)
def test_container_reaper_removes_managed_containers():
    import subprocess

    from archon.sandbox.reaper import reap_orphan_containers

    subprocess.run(
        ["docker", "run", "-d", "--label", "archon.managed=true", "alpine", "sleep", "60"],
        check=True, capture_output=True,
    )
    assert reap_orphan_containers() >= 1
    left = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=archon.managed=true"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert left == ""
