"""Phase 4 acceptance contract (spec sections 4, 24-26, 53, 56).

FULL run on the fixture: recovered churn/age/co-change, the planted hidden assumptions,
behaviour with the known test gap, classified evidence, AI provider pinned.
"""

from __future__ import annotations

from sqlalchemy import func, select

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    Assumption,
    BehaviorReconstruction,
    Commit,
    Component,
    Dependency,
    Job,
    Repository,
)
from archon.domain.enums import (
    Classification,
    ComponentKind,
    DependencyKind,
    JobState,
    RunMode,
    RunState,
    Stage,
)
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from tests.conftest import terminal_stage


def _run(test_repo) -> str:
    jobs = JobManager()
    with session_scope() as s:
        provider = provider_for(str(test_repo))
        ref = provider.parse(str(test_repo))
        repo = Repository(provider=provider.kind, url=ref.canonical_url, name=ref.name)
        s.add(repo)
        s.flush()
        rid = jobs.create_run_with_job(s, repository_id=repo.id, mode=RunMode.ANALYSIS_ONLY).run_id
    w = Worker()
    while w.tick():
        pass
    return rid


def _mod(s, sid, qn):
    return s.scalar(
        select(Component).where(
            Component.snapshot_id == sid,
            Component.qualified_name == qn,
            Component.kind == ComponentKind.MODULE,
        )
    )


def test_git_history_recovered(test_repo):
    rid = _run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is terminal_stage("ANALYSIS_ONLY")
        sid = run.snapshot_id

        assert s.scalar(select(func.count(Commit.id)).where(Commit.snapshot_id == sid)) == 3

        billing = _mod(s, sid, "legacy_shop.billing")
        calc = _mod(s, sid, "legacy_shop.calculator")
        inv = _mod(s, sid, "legacy_shop.inventory")

        # churn / change frequency
        assert billing.metrics["git"]["commit_count"] == 2   # commits 1 and 3
        assert calc.metrics["git"]["commit_count"] == 1      # commit 1 only
        assert inv.metrics["git"]["commit_count"] == 1       # commit 2

        # component age: billing/calculator (June) older than inventory (July)
        assert billing.metrics["git"]["age_days"] == calc.metrics["git"]["age_days"]
        assert billing.metrics["git"]["age_days"] > inv.metrics["git"]["age_days"]

        # co-change: billing <-> calculator (both edited in the initial commit)
        cw = {
            (s.get(Component, e.src_component_id).qualified_name,
             s.get(Component, e.dst_component_id).qualified_name)
            for e in s.scalars(
                select(Dependency).where(
                    Dependency.snapshot_id == sid,
                    Dependency.kind == DependencyKind.CHANGED_WITH,
                )
            ).all()
        }
        assert ("legacy_shop.billing", "legacy_shop.calculator") in cw
        assert ("legacy_shop.calculator", "legacy_shop.billing") in cw


def test_planted_assumptions_detected(test_repo):
    rid = _run(test_repo)
    with session_scope() as s:
        rows = s.scalars(select(Assumption).where(Assumption.run_id == rid)).all()
        assert len(rows) >= 3
        by_kind = {a.kind for a in rows}
        # the division-by-zero in calculator.divide
        div = next(a for a in rows if a.kind == "division")
        assert "calculator.py" in (div.location or "")
        # the module-level mutable global _STOCK in inventory
        assert "global_state" in by_kind
        gs = next(a for a in rows if a.kind == "global_state")
        assert "_STOCK" in gs.description and "inventory.py" in (gs.location or "")
        # inventory is untested -> its assumptions are elevated to HIGH by the mock AI
        assert gs.risk == "HIGH"
        for a in rows:
            assert a.suggested_test and a.confidence


def test_behavior_reconstruction_and_test_gap(test_repo):
    rid = _run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        sid = run.snapshot_id
        qn_by_id = {
            c.id: c.qualified_name
            for c in s.scalars(select(Component).where(Component.snapshot_id == sid)).all()
        }
        rows = s.scalars(
            select(BehaviorReconstruction).where(BehaviorReconstruction.run_id == rid)
        ).all()
        by_qn = {qn_by_id.get(b.component_id): b for b in rows}

        reserve = by_qn["legacy_shop.inventory.reserve"]
        assert "ValueError" in (reserve.exceptions or [])
        assert reserve.tests == []                       # known test gap
        assert reserve.callees and "legacy_shop.billing.line_total" in reserve.callees
        assert reserve.purpose

        billing_mod = by_qn["legacy_shop.billing"]
        assert billing_mod.git["commit_count"] == 2
        assert billing_mod.historical_context and "commit" in billing_mod.historical_context


def test_classified_evidence_and_version_pinning(test_repo):
    rid = _run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        ev = [
            e for e in run.evidence
            if e.stage in (Stage.ANALYZING_GIT, Stage.ARCHAEOLOGIZING)
        ]
        assert ev
        for e in ev:
            assert e.classification in set(Classification)
            assert e.produced_by in {"git.v1", "archaeology.v1", "assumptions.v1"}
        assert any(
            e.classification is Classification.FACT and "Analyzed 3 commit(s)" in e.summary
            for e in ev
        )
        assert any(
            e.classification is Classification.FACT
            and "hidden assumption(s)" in e.summary
            for e in ev
        )
        for name in ("git", "behavior", "assumptions", "archaeology"):
            assert run.engine_versions.get(name)
        assert run.engine_versions.get("ai_provider") == "mock"
