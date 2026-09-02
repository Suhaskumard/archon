"""The single named end-to-end acceptance test (spec section 57).

Drives ``build_test_repo`` through a full ``RunMode.FULL`` run and asserts a real,
evidence-backed row at every stage boundary of the closed loop - ingest -> source ->
git -> architecture -> scoring -> test discovery -> execution -> failure -> investigation
-> patch -> verification -> incident -> modernization -> report. Requires the Docker
sandbox (``sandbox_image_available``); skips cleanly without it.
"""

from __future__ import annotations

from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    ChangeAssessment,
    Commit,
    Component,
    Dependency,
    Failure,
    Hotspot,
    Incident,
    Investigation,
    Job,
    LegacyDNA,
    ModernizationRecommendation,
    Patch,
    PatchVerification,
    Repository,
    TestGap,
)
from archon.domain.enums import (
    ComponentKind,
    JobState,
    PatchState,
    RunMode,
    RunState,
    Stage,
    VerificationVerdict,
)
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from archon.reporting.workbook import SHEET_NAMES, build_report
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


def test_full_pipeline_end_to_end(test_repo, sandbox_image_available):
    rid = _run(test_repo)

    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert run.state is RunState.COMPLETED
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.last_completed_stage is terminal_stage("FULL") is Stage.MODERNIZING
        sid = run.snapshot_id

        # ingest / snapshot
        assert run.snapshot is not None and len(run.snapshot.commit_sha) == 40
        assert run.snapshot.support_level.value == "SUPPORTED"

        # source
        comps = s.scalars(select(Component).where(Component.snapshot_id == sid)).all()
        assert {c.kind for c in comps} >= {ComponentKind.MODULE, ComponentKind.FUNCTION}
        assert s.scalar(select(Dependency).where(Dependency.snapshot_id == sid)) is not None

        # git archaeology
        assert len(s.scalars(select(Commit).where(Commit.snapshot_id == sid)).all()) == 3

        # architecture
        assert any(
            c.role for c in comps if c.kind is ComponentKind.MODULE
        ), "at least one module has an inferred role"

        # scoring
        assert s.scalar(select(LegacyDNA).where(LegacyDNA.run_id == rid)) is not None
        assert s.scalar(select(Hotspot).where(Hotspot.run_id == rid)) is not None
        assert s.scalar(select(ChangeAssessment).where(ChangeAssessment.run_id == rid)) is not None

        # test-gap analysis - inventory.reserve is the planted untested function
        gaps = s.scalars(select(TestGap).where(TestGap.run_id == rid)).all()
        gap_comp_ids = {g.component_id for g in gaps}
        reserve = s.scalar(
            select(Component).where(
                Component.snapshot_id == sid, Component.name == "reserve"
            )
        )
        assert reserve is not None and reserve.id in gap_comp_ids

        # failure -> investigation -> patch -> verification
        failure = s.scalar(select(Failure).where(Failure.run_id == rid))
        assert failure is not None and failure.exception_type == "ZeroDivisionError"
        investigation = s.scalar(select(Investigation).where(Investigation.run_id == rid))
        divide = s.scalar(
            select(Component).where(Component.snapshot_id == sid, Component.name == "divide")
        )
        assert divide.id in investigation.affected_component_ids
        verified = [
            p for p in s.scalars(select(Patch).where(Patch.run_id == rid)).all()
            if p.state is PatchState.VERIFIED
        ]
        assert len(verified) == 1
        v = s.scalar(
            select(PatchVerification).where(PatchVerification.patch_id == verified[0].id)
        )
        assert v.verdict is VerificationVerdict.VERIFIED and v.regression_pass is True

        # incident memory + modernization
        assert len(s.scalars(select(Incident).where(Incident.run_id == rid)).all()) == 1
        assert s.scalar(
            select(ModernizationRecommendation).where(
                ModernizationRecommendation.run_id == rid
            )
        ) is not None

        # reporting: the 14-sheet workbook renders from this run
        wb = build_report(s, rid)
        assert wb.sheetnames == list(SHEET_NAMES)
