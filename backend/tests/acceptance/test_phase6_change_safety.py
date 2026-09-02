"""Phase 6 acceptance contract (spec sections 4, 31-32, 53, 60).

FULL run on the scoring fixture: a stable, well-tested component scores safer than a
coupled, unstable, untested one; Change Impact for that unstable component returns a
dependent set matching the fixture's known import graph.
"""

from __future__ import annotations

from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    ChangeAssessment,
    ChangeImpact,
    Component,
    Job,
    Repository,
)
from archon.domain.enums import ComponentKind, JobState, RunMode, RunState
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
        rid = jobs.create_run_with_job(s, repository_id=repo.id, mode=RunMode.ANALYSIS_ONLY).run_id
    w = Worker()
    while w.tick():
        pass
    return rid


def _module(s, snapshot_id, qn):
    return s.scalar(
        select(Component).where(
            Component.snapshot_id == snapshot_id,
            Component.qualified_name == qn,
            Component.kind == ComponentKind.MODULE,
        )
    )


def test_run_completes_at_analyzing_change_impact(scoring_repo):
    rid = _run(scoring_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is terminal_stage("ANALYSIS_ONLY")
        for key in ("change_safety", "change_impact"):
            assert key in run.engine_versions


def test_stable_component_scores_safer_than_coupled_unstable_one(scoring_repo):
    """spec §7 / §31 acceptance: a well-covered stable component must score safer than
    a highly-coupled, historically-unstable one."""
    rid = _run(scoring_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        sid = run.snapshot_id
        stable = _module(s, sid, "scoring_shop.tax_rules")
        unstable = _module(s, sid, "scoring_shop.pricing_engine")

        ca_stable = s.scalar(
            select(ChangeAssessment).where(
                ChangeAssessment.run_id == rid, ChangeAssessment.component_id == stable.id
            )
        )
        ca_unstable = s.scalar(
            select(ChangeAssessment).where(
                ChangeAssessment.run_id == rid, ChangeAssessment.component_id == unstable.id
            )
        )
        assert ca_stable.safety_score > ca_unstable.safety_score
        assert ca_stable.risk_category != ca_unstable.risk_category
        assert ca_stable.recommended_preparation == [
            "No specific preparation flagged - proceed with standard review."
        ]
        assert len(ca_unstable.recommended_preparation) > 0


def test_change_impact_matches_fixture_dependency_graph(scoring_repo):
    rid = _run(scoring_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        pricing = _module(s, run.snapshot_id, "scoring_shop.pricing_engine")
        ci = s.scalar(
            select(ChangeImpact).where(
                ChangeImpact.run_id == rid, ChangeImpact.component_id == pricing.id
            )
        )
        dependent_qns = {d["qualified_name"] for d in ci.direct_dependents} | {
            d["qualified_name"] for d in ci.indirect_dependents
        }
        expected = {
            "scoring_shop.checkout", "scoring_shop.invoice", "scoring_shop.promotions",
            "scoring_shop.discount_rules",
        }
        assert expected <= dependent_qns
        assert ci.related_tests == []  # pricing_engine is the known untested module
