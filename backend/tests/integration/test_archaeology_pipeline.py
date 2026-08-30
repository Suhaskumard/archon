"""ARCHAEOLOGIZING stage: behaviour + assumptions + first AI step (spec sections 24-26, 53)."""

from __future__ import annotations

from sqlalchemy import func, select

from archon.core.artifacts import read_json
from archon.db.base import session_scope
from archon.db.models import (
    AnalysisArtifact,
    AnalysisRun,
    Assumption,
    BehaviorReconstruction,
    Component,
    Job,
    Repository,
)
from archon.domain.enums import JobState, RunMode
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from tests.conftest import terminal_stage


def _full_run(test_repo, mode=RunMode.FULL) -> str:
    jobs = JobManager()
    with session_scope() as s:
        provider = provider_for(str(test_repo))
        ref = provider.parse(str(test_repo))
        repo = Repository(provider=provider.kind, url=ref.canonical_url, name=ref.name)
        s.add(repo)
        s.flush()
        rid = jobs.create_run_with_job(s, repository_id=repo.id, mode=mode).run_id
    w = Worker()
    while w.tick():
        pass
    return rid


def test_archaeology_populates_behavior_and_assumptions(test_repo):
    rid = _full_run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.last_completed_stage is terminal_stage("FULL")
        sid = run.snapshot_id

        assumptions = s.scalars(select(Assumption).where(Assumption.run_id == rid)).all()
        kinds = {a.kind for a in assumptions}
        assert "division" in kinds
        assert "global_state" in kinds
        assert len(assumptions) >= 3
        for a in assumptions:
            assert a.risk in ("HIGH", "MEDIUM", "LOW")
            assert a.suggested_test
            assert a.produced_by == "assumptions.v1"

        behaviors = s.scalars(
            select(BehaviorReconstruction).where(BehaviorReconstruction.run_id == rid)
        ).all()
        assert len(behaviors) >= 8
        qn_by_id = {
            c.id: c.qualified_name
            for c in s.scalars(select(Component).where(Component.snapshot_id == sid)).all()
        }
        reserve = next(
            b for b in behaviors
            if qn_by_id.get(b.component_id) == "legacy_shop.inventory.reserve"
        )
        assert "ValueError" in (reserve.exceptions or [])
        assert reserve.tests == []  # the known test gap
        assert reserve.purpose and reserve.classification in (
            "FACT", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"
        )
        assert reserve.git and reserve.git.get("commit_count") == 1  # inventory: 1 commit

        art = s.scalar(
            select(AnalysisArtifact).where(
                AnalysisArtifact.run_id == rid, AnalysisArtifact.kind == "archaeology"
            )
        )
        doc = read_json(art)
        assert doc["schema"] == "archon.archaeology.v1"
        assert len(doc["assumptions"]) == len(assumptions)

        assert any("hidden assumption(s)" in e.summary for e in run.evidence)
        assert run.engine_versions.get("ai_provider") == "mock"
        assert run.engine_versions.get("archaeology") == "archaeology.v1"


def test_archaeology_cached_by_copying_rows(test_repo):
    r1 = _full_run(test_repo)
    with session_scope() as s:
        run1 = s.get(AnalysisRun, r1)
        b1 = s.scalar(
            select(func.count(BehaviorReconstruction.id)).where(
                BehaviorReconstruction.run_id == r1
            )
        )
        a1 = s.scalar(select(func.count(Assumption.id)).where(Assumption.run_id == r1))
        job = JobManager().create_run_with_job(
            s, repository_id=run1.repository_id, mode=RunMode.FULL, config_hash="v2"
        )
        r2 = job.run_id
    w = Worker()
    while w.tick():
        pass
    with session_scope() as s:
        assert s.scalar(
            select(func.count(BehaviorReconstruction.id)).where(
                BehaviorReconstruction.run_id == r2
            )
        ) == b1
        assert s.scalar(select(func.count(Assumption.id)).where(Assumption.run_id == r2)) == a1
        assert any(
            "Reused cached archaeology" in e.summary
            for e in s.get(AnalysisRun, r2).evidence
        )


def test_ingest_only_skips_archaeology(test_repo):
    rid = _full_run(test_repo, mode=RunMode.INGEST_ONLY)
    with session_scope() as s:
        assert s.scalar(select(func.count(Assumption.id)).where(Assumption.run_id == rid)) == 0
