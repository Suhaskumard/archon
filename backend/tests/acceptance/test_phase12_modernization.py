"""Phase 12 acceptance contract (spec section 46).

A full run over the ``scoring_shop`` fixture (whose ``pricing_engine`` is untested,
high fan-in, in an import cycle with ``discount_rules``, and carries planted
BROAD_EXCEPT / HARDCODED_CONFIG / MAGIC_NUMBER debt) ends with a MODERNIZING stage
that produces an ordered, evidence-backed plan:

* ``pricing_engine`` gets both an ADD_TESTS and a REFACTOR recommendation, and
  ADD_TESTS is ordered before REFACTOR ("add tests before refactor");
* no REWRITE recommendation exists anywhere - cheaper safe options applied
  (Principle 12).

Requires the real Docker sandbox (a FULL run reaches COMPLETED only with it).
"""

from __future__ import annotations

from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import AnalysisRun, Evidence, Job, ModernizationRecommendation, Repository
from archon.domain.enums import JobState, RunMode, RunState, Stage
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from tests.conftest import terminal_stage


def _run(repo_id: str) -> str:
    jobs = JobManager()
    with session_scope() as s:
        rid = jobs.create_run_with_job(s, repository_id=repo_id, mode=RunMode.FULL).run_id
    w = Worker()
    while w.tick():
        pass
    return rid


def test_modernization_plan_orders_add_tests_before_refactor(
    scoring_repo, sandbox_image_available
):
    with session_scope() as s:
        provider = provider_for(str(scoring_repo))
        ref = provider.parse(str(scoring_repo))
        repo = Repository(provider=provider.kind, url=ref.canonical_url, name=ref.name)
        s.add(repo)
        s.flush()
        repo_id = repo.id

    rid = _run(repo_id)

    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert run.state is RunState.COMPLETED
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        # MODERNIZING is now the pipeline's terminal stage
        assert run.last_completed_stage is terminal_stage("FULL") is Stage.MODERNIZING
        assert "modernization" in run.engine_versions

        recs = s.scalars(
            select(ModernizationRecommendation)
            .where(ModernizationRecommendation.run_id == rid)
            .order_by(ModernizationRecommendation.order_index)
        ).all()
        assert recs, "expected at least one modernization recommendation"

        by_target: dict[str, dict[str, int]] = {}
        for r in recs:
            by_target.setdefault(r.target, {})[r.strategy.value] = r.order_index

        pricing = next(
            (v for t, v in by_target.items() if t.endswith(".pricing_engine")), None
        )
        assert pricing is not None, f"pricing_engine not in {list(by_target)}"
        assert "ADD_TESTS" in pricing and "REFACTOR" in pricing
        assert pricing["ADD_TESTS"] < pricing["REFACTOR"]

        # rewrite is never chosen when a cheaper safe option exists
        assert "REWRITE" not in {r.strategy.value for r in recs}

        # every recommendation is evidence-backed
        ev = s.scalars(
            select(Evidence).where(
                Evidence.run_id == rid, Evidence.stage == Stage.MODERNIZING
            )
        ).all()
        assert len(ev) >= len(recs)
        assert all(r.evidence_ids for r in recs)
        assert all(0.0 <= r.confidence <= 1.0 for r in recs)
