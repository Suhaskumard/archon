"""Phase 7 acceptance contract (spec sections 4, 12, 36, 53, 60).

The malicious fixture (network call, fork-bomb attempt, secret-read attempt,
filesystem-escape attempt) is contained and reported with zero host-visible side
effects; a normal pytest suite runs through the full pipeline and its results are
captured accurately.
"""

from __future__ import annotations

from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import AnalysisRun, Execution, Job, Repository, TestCase
from archon.domain.enums import ExecutionKind, JobState, RunMode, RunState, TestCaseKind
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from archon.sandbox.base import ExecutionSpec
from archon.sandbox.docker_sandbox import DockerSandbox
from archon.workspace.manager import WorkspaceManager
from tests.conftest import terminal_stage


def _run(repo_path) -> str:
    jobs = JobManager()
    with session_scope() as s:
        provider = provider_for(str(repo_path))
        ref = provider.parse(str(repo_path))
        repo = Repository(provider=provider.kind, url=ref.canonical_url, name=ref.name)
        s.add(repo)
        s.flush()
        rid = jobs.create_run_with_job(s, repository_id=repo.id, mode=RunMode.FULL).run_id
    w = Worker()
    while w.tick():
        pass
    return rid


def test_run_completes_at_executing(test_repo, sandbox_image_available):
    rid = _run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is terminal_stage("FULL")
        for key in ("test_discovery", "execution", "characterization", "test_generation"):
            assert key in run.engine_versions


def test_normal_suite_runs_and_results_are_captured(test_repo, sandbox_image_available):
    rid = _run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        # Phase 8 adds characterization/AI-generated TestCase rows on top of the 3
        # existing ones discovered by Phase 7 - this contract is about EXISTING only.
        # Phase 9 plants a genuinely-failing test (test_divide_by_zero_returns_none) -
        # discovery still finds it (discovery != pass/fail), so the count is 3.
        test_cases = s.scalars(
            select(TestCase).where(TestCase.run_id == rid, TestCase.kind == TestCaseKind.EXISTING)
        ).all()
        assert len(test_cases) == 3
        assert {tc.name for tc in test_cases} == {
            "tests.test_calculator.test_add", "tests.test_billing.test_line_total",
            "tests.test_calculator.test_divide_by_zero_returns_none",
        }

        execution = s.scalar(
            select(Execution).where(Execution.run_id == rid, Execution.kind == ExecutionKind.EXISTING_TESTS)
        )
        assert execution is not None
        assert execution.exit_code != 0  # the planted failure makes the suite fail
        assert execution.passed == 2
        assert execution.failed == 1
        assert execution.errors == 0
        assert execution.timed_out is False
        assert execution.stdout_ref is not None
        assert execution.coverage_ref is not None
        assert run.snapshot_id  # sanity: the run actually reached a real snapshot


def test_malicious_fixture_is_contained_with_no_host_side_effects(
    malicious_repo, sandbox_image_available, monkeypatch
):
    monkeypatch.setenv("ARCHON_GITHUB_TOKEN", "ghp_fake_secret_should_never_leak")

    wm = WorkspaceManager()
    ws = wm.create("malicious")
    try:
        import shutil

        shutil.copytree(malicious_repo, ws.resolve_within("repo"), dirs_exist_ok=True)
        sandbox = DockerSandbox("archon-sandbox:latest")
        spec = ExecutionSpec(
            workspace=ws,
            command=["python3", "-m", "pytest", "-q", "--tb=line", "test_malicious.py"],
            timeout_seconds=30, pids_limit=32,
        )
        result = sandbox.run(spec)
    finally:
        wm.cleanup(ws)

    # contained: all four malicious tests failed/errored, fast, no wall-clock kill needed
    assert result.exit_code != 0
    assert result.timed_out is False
    assert "test_network_call" in result.stdout
    assert "test_fork_bomb" in result.stdout
    assert "test_secret_read" in result.stdout
    assert "test_fs_escape" in result.stdout

    # the empty-env guarantee is real, not assumed: the host's fake secret never leaked
    assert "ghp_fake_secret_should_never_leak" not in result.stdout
    assert "ghp_fake_secret_should_never_leak" not in result.stderr
    assert "ARCHON_GITHUB_TOKEN" not in result.stdout
