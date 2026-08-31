"""Phase 8 acceptance contract (spec sections 4, 33-35, 53, 60).

The fixture's known test gap (``legacy_shop/inventory.py::reserve``, marked
``# KNOWN TEST GAP`` in ``build_test_repo.py``) is found and ranked; a characterization
baseline is reproducible run-to-run; at least one AI-generated test is validated.
Requires the real Docker sandbox (``sandbox_image_available``) - characterization and
AI test generation both execute inside it.
"""

from __future__ import annotations

from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    Characterization,
    Component,
    Job,
    Repository,
    TestCase,
    TestGap,
)
from archon.domain.enums import JobState, RunMode, RunState, TestCaseOrigin
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


def test_known_test_gap_is_found_and_prioritized(test_repo, sandbox_image_available):
    rid = _run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is terminal_stage("FULL")

        gaps = s.scalars(select(TestGap).where(TestGap.run_id == rid)).all()
        reserve = s.scalar(
            select(Component).where(
                Component.snapshot_id == run.snapshot_id, Component.name == "reserve",
            )
        )
        assert reserve is not None
        reserve_gap = next((g for g in gaps if g.component_id == reserve.id), None)
        assert reserve_gap is not None, "known test gap (inventory.reserve) was not found"
        assert reserve_gap.kind.value == "UNTESTED_FUNCTION"
        assert reserve_gap.coverage_pct == 0.0
        assert reserve_gap.priority_score > 0.0
        assert reserve_gap.priority in ("MEDIUM", "HIGH", "CRITICAL")  # ranked above the floor


def test_characterization_baseline_is_reproducible(test_repo, sandbox_image_available):
    rid1 = _run(test_repo)
    with session_scope() as s:
        run1 = s.get(AnalysisRun, rid1)
        repo_id = run1.repository_id

    jobs = JobManager()
    with session_scope() as s:
        rid2 = jobs.create_run_with_job(s, repository_id=repo_id, mode=RunMode.FULL).run_id
    w = Worker()
    while w.tick():
        pass

    with session_scope() as s:
        run1 = s.get(AnalysisRun, rid1)
        run2 = s.get(AnalysisRun, rid2)
        assert run2.state is RunState.COMPLETED
        assert run1.snapshot_id == run2.snapshot_id  # a second run over the identical commit

        reserve = s.scalar(
            select(Component).where(
                Component.snapshot_id == run1.snapshot_id, Component.name == "reserve",
            )
        )
        c1 = s.scalar(
            select(Characterization).where(
                Characterization.run_id == rid1, Characterization.component_id == reserve.id,
            )
        )
        c2 = s.scalar(
            select(Characterization).where(
                Characterization.run_id == rid2, Characterization.component_id == reserve.id,
            )
        )
        assert c1 is not None and c2 is not None
        assert c1.baseline_hash == c2.baseline_hash


def test_at_least_one_ai_generated_test_is_validated(test_repo, sandbox_image_available):
    rid = _run(test_repo)
    with session_scope() as s:
        ai_tests = s.scalars(
            select(TestCase).where(TestCase.run_id == rid, TestCase.origin == TestCaseOrigin.AI)
        ).all()
        assert ai_tests, "no AI-generated test cases were produced"
        assert any(tc.validated for tc in ai_tests)
