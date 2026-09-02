"""Phase 6 pipeline integration tests: stages persist rows, cache-reuse works, engine
versions are pinned (spec sections 31-32, 53)."""

from __future__ import annotations

from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import AnalysisRun, ChangeAssessment, ChangeImpact, Component, Repository
from archon.domain.enums import ComponentKind, RunMode, RunState
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


def test_run_completes_with_phase6_rows(scoring_repo):
    rid = _run(scoring_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is terminal_stage("ANALYSIS_ONLY")
        for key in ("change_safety", "change_impact"):
            assert key in run.engine_versions

        assert s.scalar(select(ChangeAssessment).where(ChangeAssessment.run_id == rid).limit(1)) is not None
        assert s.scalar(select(ChangeImpact).where(ChangeImpact.run_id == rid).limit(1)) is not None


def test_change_impact_precomputed_for_every_module(scoring_repo):
    rid = _run(scoring_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        module_ids = set(
            s.scalars(
                select(Component.id).where(
                    Component.snapshot_id == run.snapshot_id, Component.kind == ComponentKind.MODULE
                )
            ).all()
        )
        impacted_ids = set(
            s.scalars(select(ChangeImpact.component_id).where(ChangeImpact.run_id == rid)).all()
        )
        assert module_ids <= impacted_ids


def test_second_run_over_same_snapshot_clones_change_safety(scoring_repo):
    rid1 = _run(scoring_repo)
    with session_scope() as s:
        run1 = s.get(AnalysisRun, rid1)
        repo_id = run1.repository_id
        snapshot_id = run1.snapshot_id

    jobs = JobManager()
    with session_scope() as s:
        rid2 = jobs.create_run_with_job(s, repository_id=repo_id, mode=RunMode.ANALYSIS_ONLY).run_id
    w = Worker()
    while w.tick():
        pass

    with session_scope() as s:
        run2 = s.get(AnalysisRun, rid2)
        assert run2.state is RunState.COMPLETED
        assert run2.snapshot_id == snapshot_id

        rows1 = {
            r.component_id: r.factor_breakdown
            for r in s.scalars(select(ChangeAssessment).where(ChangeAssessment.run_id == rid1)).all()
        }
        rows2 = {
            r.component_id: r.factor_breakdown
            for r in s.scalars(select(ChangeAssessment).where(ChangeAssessment.run_id == rid2)).all()
        }
        assert rows1.keys() == rows2.keys()
        for cid, breakdown1 in rows1.items():
            assert breakdown1 == rows2[cid], f"factor_breakdown diverged for {cid}"


def test_pricing_engine_less_safe_than_tax_rules(scoring_repo):
    rid = _run(scoring_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        pricing = s.scalar(
            select(Component).where(
                Component.snapshot_id == run.snapshot_id,
                Component.qualified_name == "scoring_shop.pricing_engine",
                Component.kind == ComponentKind.MODULE,
            )
        )
        tax = s.scalar(
            select(Component).where(
                Component.snapshot_id == run.snapshot_id,
                Component.qualified_name == "scoring_shop.tax_rules",
                Component.kind == ComponentKind.MODULE,
            )
        )
        ca_pricing = s.scalar(
            select(ChangeAssessment).where(ChangeAssessment.run_id == rid, ChangeAssessment.component_id == pricing.id)
        )
        ca_tax = s.scalar(
            select(ChangeAssessment).where(ChangeAssessment.run_id == rid, ChangeAssessment.component_id == tax.id)
        )
        assert ca_tax.safety_score > ca_pricing.safety_score
        assert ca_tax.risk_category != ca_pricing.risk_category
