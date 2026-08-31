"""Phase 9 acceptance contract (spec sections 4, 37-43, 53, 60).

The fixture's planted, reproducible bug (``calculator.divide`` has no zero-divisor
guard, exercised by ``test_divide_by_zero_returns_none``) is detected, investigated
(naming the real root cause), patched by two deterministic candidates, ranked, and
verified: the correct guard reaches VERIFIED, the deliberately-wrong candidate is
REJECTED and rolled back (its clone workspace discarded, original repo never touched).
Requires the real Docker sandbox (``sandbox_image_available``).
"""

from __future__ import annotations

import os

from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    Component,
    Failure,
    Investigation,
    Job,
    Patch,
    PatchVerification,
    Repository,
)
from archon.domain.enums import JobState, PatchState, RunMode, RunState, VerificationVerdict
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
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


def _snapshot_files(repo_dir):
    files = {}
    for root, _dirs, names in os.walk(repo_dir):
        for name in names:
            p = os.path.join(root, name)
            files[os.path.relpath(p, repo_dir)] = os.path.getmtime(p)
    return files


def test_planted_bug_is_healed_end_to_end(test_repo, sandbox_image_available):
    original_files = _snapshot_files(test_repo)

    rid = _run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is terminal_stage("FULL")

        # 1. Failure detected
        failures = s.scalars(select(Failure).where(Failure.run_id == rid)).all()
        assert len(failures) == 1
        failure = failures[0]
        assert failure.test_identifier == "tests.test_calculator.test_divide_by_zero_returns_none"
        assert failure.exception_type == "ZeroDivisionError"
        assert failure.reproducible is True

        # 2. Investigation names the planted root cause
        investigation = s.scalar(select(Investigation).where(Investigation.failure_id == failure.id))
        assert investigation is not None
        assert investigation.confidence >= 0.6
        divide = s.scalar(
            select(Component).where(
                Component.snapshot_id == run.snapshot_id, Component.name == "divide",
            )
        )
        assert divide.id in investigation.affected_component_ids
        assert "division" in investigation.summary.lower()

        # 3. Two ranked candidate patches
        patches = s.scalars(select(Patch).where(Patch.run_id == rid)).all()
        assert {p.strategy for p in patches} == {"guard_zero_divisor", "naive_integer_division"}
        for p in patches:
            assert p.rank_score is not None
            assert p.static_validation["parses"]

        # 4. Verification: guard VERIFIED, naive REJECTED
        verifications = {
            s.get(Patch, v.patch_id).strategy: v
            for v in s.scalars(select(PatchVerification).where(PatchVerification.run_id == rid)).all()
        }
        assert set(verifications) == {"guard_zero_divisor", "naive_integer_division"}

        guard_v = verifications["guard_zero_divisor"]
        assert guard_v.verdict is VerificationVerdict.VERIFIED
        assert guard_v.original_failure_fixed is True
        assert guard_v.regression_pass is True
        assert guard_v.existing_tests_pass is True
        assert guard_v.characterization_pass is True
        assert guard_v.applies_cleanly is True

        naive_v = verifications["naive_integer_division"]
        assert naive_v.verdict is VerificationVerdict.REJECTED
        assert naive_v.original_failure_fixed is False

        guard_patch = next(p for p in patches if p.strategy == "guard_zero_divisor")
        naive_patch = next(p for p in patches if p.strategy == "naive_integer_division")
        assert guard_patch.state is PatchState.VERIFIED
        assert naive_patch.state is PatchState.REJECTED

    # 5. The original repository checkout was never modified by verification/rollback
    # (patches are only ever applied to throwaway WorkspaceManager.clone() copies).
    assert _snapshot_files(test_repo) == original_files
    calculator_src = (test_repo / "legacy_shop" / "calculator.py").read_text(encoding="utf-8")
    assert "BUG: no guard for b == 0" in calculator_src
    assert "if b == 0" not in calculator_src
