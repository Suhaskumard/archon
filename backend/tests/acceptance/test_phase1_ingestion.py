"""Phase 1 acceptance contract (spec sections 4, 17, 21, 54, 56).

A repository is ingested through the real pipeline and the resulting snapshot, evidence
and error behaviour are asserted against the plan's Phase 1 acceptance criteria:

* GitHub-style URL / local path -> validated Repository row
* secure clone -> immutable RepositorySnapshot pinned to a real commit SHA
* support level classified with a documented reason set
* every conclusion recorded as Evidence with a Classification
* failure modes (bad URL, missing repo, non-git dir) return structured errors, never
  a bare stack trace, and are never silently swallowed
"""

from __future__ import annotations

import pytest

from archon.core.errors import ArchonError, ErrorCode
from archon.db.base import session_scope
from archon.db.models import AnalysisRun, Job, Repository, RepositorySnapshot
from archon.domain.enums import Classification, JobState, RunMode, RunState
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from archon.providers.repo.local import LocalRepositoryProvider


def _ingest(path, *, ref=None) -> str:
    jobs = JobManager()
    provider = provider_for(str(path))
    parsed = provider.parse(str(path), ref=ref)
    with session_scope() as session:
        repo = Repository(provider=provider.kind, url=parsed.canonical_url, name=parsed.name)
        session.add(repo)
        session.flush()
        job = jobs.create_run_with_job(
            session, repository_id=repo.id, requested_ref=ref, mode=RunMode.INGEST_ONLY
        )
        run_id = job.run_id
    w = Worker()
    while w.tick():
        pass
    return run_id


def test_end_to_end_ingestion_produces_evidence_backed_snapshot(test_repo):
    run_id = _ingest(test_repo)

    with session_scope() as session:
        run = session.get(AnalysisRun, run_id)
        job = session.get(Job, run.job.id)
        snap = session.get(RepositorySnapshot, run.snapshot_id)

        # run + job both reached a clean terminal state
        assert run.state is RunState.COMPLETED
        assert job.state is JobState.SUCCEEDED
        assert run.error is None

        # immutable snapshot pinned to a real 40-hex commit sha
        assert snap is not None
        assert len(snap.commit_sha) == 40 and int(snap.commit_sha, 16) >= 0
        assert snap.branch == "main"
        assert snap.commit_count == 3
        assert snap.workspace_ref  # checkout preserved for later phases

        # support contract (spec section 17) with a documented note set
        assert snap.support_level.value == "SUPPORTED"
        assert snap.support_notes["python_ratio"] >= 0.5
        assert "reasons" in snap.support_notes

        # every conclusion is classified evidence (spec section 4)
        assert len(run.evidence) >= 2
        for ev in run.evidence:
            assert ev.classification in set(Classification)
            assert ev.produced_by
        assert any(e.refs and "commit_sha" in e.refs for e in run.evidence)

        # engine versions were snapshotted for reproducibility (spec section 53)
        assert run.engine_versions.get("ingestion") == "ingestion.v1"


def test_reingesting_same_commit_reuses_the_snapshot(test_repo):
    r1 = _ingest(test_repo)
    with session_scope() as session:
        # second run with a different config so the dedupe guard allows it
        repo_id = session.get(AnalysisRun, r1).repository_id
        job = JobManager().create_run_with_job(
            session, repository_id=repo_id, config_hash="v2", mode=RunMode.INGEST_ONLY
        )
        r2 = job.run_id
    while Worker().tick():
        pass
    with session_scope() as session:
        assert session.get(AnalysisRun, r1).snapshot_id == session.get(AnalysisRun, r2).snapshot_id
        assert session.query(RepositorySnapshot).count() == 1


@pytest.mark.parametrize(
    "target,expected_code",
    [
        ("definitely not a url", ErrorCode.INVALID_REPOSITORY_URL),
        ("https://gitlab.com/foo/bar", ErrorCode.INVALID_REPOSITORY_URL),
    ],
)
def test_bad_targets_raise_structured_errors(target, expected_code):
    with pytest.raises(ArchonError) as exc:
        provider_for(target)
    assert exc.value.code is expected_code
    body = exc.value.to_dict()["error"]
    assert body["message"] and body["suggested_action"]
    assert body["recoverability"] in {"RECOVERABLE", "NON_RECOVERABLE", "TRANSIENT"}


def test_non_git_directory_is_rejected(tmp_path):
    (tmp_path / "file.py").write_text("x = 1\n")
    with pytest.raises(ArchonError) as exc:
        LocalRepositoryProvider().parse(str(tmp_path))
    assert exc.value.code is ErrorCode.NO_GIT_HISTORY


def test_pipeline_failure_is_recorded_not_swallowed(test_repo, monkeypatch):
    """If a stage raises, the run ends FAILED with a structured error payload."""
    from archon.pipeline import orchestrator as orch

    def boom(self, session, run, repository):
        raise ArchonError(
            ErrorCode.CLONE_FAILED,
            "simulated clone failure",
            suggested_action="retry",
        )

    monkeypatch.setattr(orch.PipelineOrchestrator, "_ingest", boom)

    run_id = _ingest(test_repo)
    with session_scope() as session:
        run = session.get(AnalysisRun, run_id)
        assert run.state is RunState.FAILED
        assert run.error["code"] == "CLONE_FAILED"
        assert run.error["message"] == "simulated clone failure"
