"""Phase 5 pipeline integration tests: stages persist rows, cache-reuse works, engine
versions are pinned (spec sections 27-30, 53)."""

from __future__ import annotations

from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    Component,
    Hotspot,
    LegacyDNA,
    Repository,
    RiskAssessment,
    TechnicalDebtFinding,
)
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
        rid = jobs.create_run_with_job(s, repository_id=repo.id, mode=RunMode.FULL).run_id
    w = Worker()
    while w.tick():
        pass
    return rid


def test_run_completes_with_all_phase5_rows(scoring_repo):
    rid = _run(scoring_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is terminal_stage("FULL")
        for key in ("legacy_risk", "hotspot", "understanding", "tech_debt"):
            assert key in run.engine_versions

        assert s.scalar(select(LegacyDNA).where(LegacyDNA.run_id == rid).limit(1)) is not None
        assert s.scalar(select(RiskAssessment).where(RiskAssessment.run_id == rid).limit(1)) is not None
        assert s.scalar(select(Hotspot).where(Hotspot.run_id == rid).limit(1)) is not None
        assert s.scalar(
            select(TechnicalDebtFinding).where(TechnicalDebtFinding.run_id == rid).limit(1)
        ) is not None


def test_risk_assessment_mirrors_legacy_dna(scoring_repo):
    rid = _run(scoring_repo)
    with session_scope() as s:
        dna_rows = s.scalars(select(LegacyDNA).where(LegacyDNA.run_id == rid)).all()
        risk_rows = {
            r.component_id: r
            for r in s.scalars(
                select(RiskAssessment).where(
                    RiskAssessment.run_id == rid, RiskAssessment.engine_version == "legacy_risk.v1"
                )
            ).all()
        }
        assert len(dna_rows) == len(risk_rows)
        for dna in dna_rows:
            ra = risk_rows[dna.component_id]
            assert ra.score == dna.legacy_risk_score
            assert ra.category == dna.category


def test_second_run_over_same_snapshot_reuses_rows(scoring_repo):
    rid1 = _run(scoring_repo)
    with session_scope() as s:
        run1 = s.get(AnalysisRun, rid1)
        snapshot_id = run1.snapshot_id
        repo_id = run1.repository_id
        n_dna_1 = s.scalar(
            select(Component.id).where(Component.snapshot_id == snapshot_id)
        )  # sanity: snapshot has components
        assert n_dna_1 is not None

    jobs = JobManager()
    with session_scope() as s:
        rid2 = jobs.create_run_with_job(s, repository_id=repo_id, mode=RunMode.FULL).run_id
    w = Worker()
    while w.tick():
        pass

    with session_scope() as s:
        run2 = s.get(AnalysisRun, rid2)
        assert run2.state is RunState.COMPLETED
        assert run2.snapshot_id == snapshot_id
        dna_count_1 = s.scalar(select(LegacyDNA.id).where(LegacyDNA.run_id == rid1)) is not None
        dna_count_2 = s.scalar(select(LegacyDNA.id).where(LegacyDNA.run_id == rid2)) is not None
        assert dna_count_1 and dna_count_2

        debt_2 = s.scalars(
            select(TechnicalDebtFinding).where(TechnicalDebtFinding.run_id == rid2)
        ).all()
        debt_1 = s.scalars(
            select(TechnicalDebtFinding).where(TechnicalDebtFinding.run_id == rid1)
        ).all()
        assert len(debt_1) == len(debt_2)

        hot_1 = s.scalars(select(Hotspot).where(Hotspot.run_id == rid1)).all()
        hot_2 = s.scalars(select(Hotspot).where(Hotspot.run_id == rid2)).all()
        assert len(hot_1) == len(hot_2)


def test_pricing_engine_scored_high_risk(scoring_repo):
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
        dna_pricing = s.scalar(select(LegacyDNA).where(LegacyDNA.run_id == rid, LegacyDNA.component_id == pricing.id))
        dna_tax = s.scalar(select(LegacyDNA).where(LegacyDNA.run_id == rid, LegacyDNA.component_id == tax.id))
        assert dna_pricing.legacy_risk_score > dna_tax.legacy_risk_score
        assert dna_pricing.category in ("HIGH", "CRITICAL")
        assert dna_tax.category in ("LOW", "MODERATE")
