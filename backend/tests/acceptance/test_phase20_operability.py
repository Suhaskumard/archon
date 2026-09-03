"""Phase 20 acceptance: multi-language contract, crash recovery, stage metrics.

Sandbox-free (ANALYSIS_ONLY / INGEST_ONLY) so it runs without Docker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from archon.db.base import session_scope
from archon.db.models import AnalysisRun, Job, Repository
from archon.domain.enums import JobState, RunMode, RunState, SupportLevel
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from tests.conftest import terminal_stage


def _register(session, path) -> Repository:
    prov = provider_for(str(path))
    ref = prov.parse(str(path))
    repo = Repository(provider=prov.kind, url=ref.canonical_url, name=ref.name)
    session.add(repo)
    session.flush()
    return repo


def _drain(max_ticks: int = 25) -> None:
    w = Worker()
    for _ in range(max_ticks):
        if not w.tick():
            break


def test_polyglot_repo_yields_python_analysis_plus_non_python_summary(polyglot_repo):
    jobs = JobManager()
    with session_scope() as session:
        repo = _register(session, polyglot_repo)
        run_id = jobs.create_run_with_job(
            session, repository_id=repo.id, mode=RunMode.ANALYSIS_ONLY, config_hash="p20a"
        ).run_id

    _drain()

    with session_scope() as session:
        run = session.get(AnalysisRun, run_id)
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is terminal_stage("ANALYSIS_ONLY")
        assert run.snapshot.support_level is SupportLevel.PARTIALLY_SUPPORTED

        summaries = [
            e for e in run.evidence
            if e.summary.startswith("NON_PYTHON_SUMMARY")
        ]
        assert len(summaries) == 1
        ev = summaries[0]
        assert "JavaScript" in ev.detail and "Go" in ev.detail
        assert ev.refs["language_breakdown"]["Python"] >= 1

        # the Python slice was still really analysed
        from archon.db.models import Component

        comps = session.query(Component).filter_by(snapshot_id=run.snapshot_id).count()
        assert comps > 0


def test_run_exceeding_max_analysis_duration_fails_with_a_structured_timeout(
    test_repo, monkeypatch
):
    monkeypatch.setenv("ARCHON_LIMIT_MAX_ANALYSIS_DURATION_SECONDS", "0")
    from archon.config import reset_settings_cache

    reset_settings_cache()
    jobs = JobManager()
    with session_scope() as session:
        repo = _register(session, test_repo)
        run_id = jobs.create_run_with_job(
            session, repository_id=repo.id, mode=RunMode.ANALYSIS_ONLY, config_hash="p20b"
        ).run_id

    _drain()

    with session_scope() as session:
        run = session.get(AnalysisRun, run_id)
        assert run.state is RunState.FAILED
        assert run.error["code"] == "TIMEOUT"
        assert run.error["context"]["limit_seconds"] == 0


def test_worker_crash_mid_run_is_requeued_and_resumes_to_completed(test_repo, monkeypatch):
    monkeypatch.setenv("ARCHON_JOB_HEARTBEAT_TIMEOUT_SECONDS", "1")
    from archon.config import reset_settings_cache

    reset_settings_cache()
    jobs = JobManager()
    with session_scope() as session:
        repo = _register(session, test_repo)
        job = jobs.create_run_with_job(
            session, repository_id=repo.id, mode=RunMode.ANALYSIS_ONLY, config_hash="p20c"
        )
        run_id, job_id = job.run_id, job.id

    # simulate a worker that claimed the job then died: RUNNING with a stale heartbeat
    with session_scope() as session:
        j = session.get(Job, job_id)
        j.state = JobState.RUNNING
        j.attempts = 1
        j.started_at = datetime.now(UTC) - timedelta(minutes=5)
        j.heartbeat_at = datetime.now(UTC) - timedelta(minutes=5)
        session.get(AnalysisRun, run_id).state = RunState.RUNNING

    # a fresh worker: requeue_stale (in tick) rescues it, then it runs to completion
    _drain()

    with session_scope() as session:
        run = session.get(AnalysisRun, run_id)
        j = session.get(Job, job_id)
        assert run.state is RunState.COMPLETED
        assert j.state is JobState.SUCCEEDED
        assert run.last_completed_stage is terminal_stage("ANALYSIS_ONLY")


def test_stage_duration_and_outcome_metrics_are_recorded_after_a_run(test_repo):
    from archon.core.observability import render_metrics, reset_metrics

    reset_metrics()
    jobs = JobManager()
    with session_scope() as session:
        repo = _register(session, test_repo)
        jobs.create_run_with_job(
            session, repository_id=repo.id, mode=RunMode.INGEST_ONLY, config_hash="p20d"
        )
    _drain()

    body = render_metrics()[0].decode()
    assert 'stage="INGESTING"' in body
    assert 'stage="SNAPSHOTTING"' in body
    assert 'archon_run_outcomes_total{mode="INGEST_ONLY",outcome="completed"} 1.0' in body
