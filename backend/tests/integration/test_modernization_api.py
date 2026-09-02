"""Phase 12 - modernization API (spec sections 46, 47).

Builds an analysis-scored run directly (no sandbox needed - modernization only reads
analysis-stage rows), runs the planner, and exercises the endpoint + guards.
"""

from __future__ import annotations

from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    ChangeAssessment,
    Component,
    Dependency,
    Evidence,
    LegacyDNA,
    ModernizationRecommendation,
    Repository,
    RepositorySnapshot,
    TechnicalDebtFinding,
)
from archon.domain.enums import (
    ComponentKind,
    DependencyKind,
    ProviderKind,
    RunMode,
    RunState,
    Stage,
    TechDebtCategory,
    TechDebtSeverity,
)
from archon.modernization.planner import generate_modernization_plan


def _seed_plan(url: str = "/tmp/mod-api") -> tuple[str, str]:
    with session_scope() as s:
        repo = Repository(provider=ProviderKind.LOCAL, url=url, name="mod")
        s.add(repo)
        s.flush()
        snap = RepositorySnapshot(repository_id=repo.id, commit_sha="a" * 40)
        s.add(snap)
        s.flush()
        run = AnalysisRun(
            repository_id=repo.id, snapshot_id=snap.id, mode=RunMode.ANALYSIS_ONLY,
            state=RunState.COMPLETED, last_completed_stage=Stage.MODERNIZING,
        )
        s.add(run)
        s.flush()

        comps = {}
        for qn in ("shop.engine", "shop.consumer"):
            c = Component(
                snapshot_id=snap.id, kind=ComponentKind.MODULE, name=qn.split(".")[-1],
                qualified_name=qn, path=qn.replace(".", "/") + ".py",
            )
            s.add(c)
            s.flush()
            comps[qn] = c
        s.add(Dependency(
            snapshot_id=snap.id, src_component_id=comps["shop.consumer"].id,
            dst_component_id=comps["shop.engine"].id, kind=DependencyKind.IMPORTS,
            target_name="shop.engine",
        ))
        # engine: untested + HIGH risk + a refactor smell -> add_tests + refactor
        s.add(LegacyDNA(
            run_id=run.id, snapshot_id=snap.id, component_id=comps["shop.engine"].id,
            coverage=0.0, complexity=15, coupling=10, legacy_risk_score=82.0,
            category="HIGH", confidence=0.9, produced_by="legacy_risk.v1",
        ))
        s.add(ChangeAssessment(
            run_id=run.id, snapshot_id=snap.id, component_id=comps["shop.engine"].id,
            engine_version="change_safety.v1", safety_score=35.0, risk_category="RISKY",
            recommended_preparation=["add characterization tests"], confidence=0.9,
            produced_by="change_safety.v1",
        ))
        s.add(TechnicalDebtFinding(
            run_id=run.id, snapshot_id=snap.id, component_id=comps["shop.engine"].id,
            category=TechDebtCategory.BROAD_EXCEPT, location="shop/engine.py:12",
            severity=TechDebtSeverity.MEDIUM, confidence=0.8, produced_by="tech_debt.v1",
        ))
        s.flush()

        generate_modernization_plan(s, run, snap)
        return repo.id, run.id


def test_modernization_endpoint_returns_ordered_rows(client):
    _repo, run_id = _seed_plan()
    rows = client.get(f"/runs/{run_id}/modernization").json()
    assert len(rows) >= 2
    assert [r["order_index"] for r in rows] == sorted(r["order_index"] for r in rows)

    engine = [r for r in rows if r["target"] == "shop.engine"]
    strategies = {r["strategy"] for r in engine}
    assert "ADD_TESTS" in strategies and "REFACTOR" in strategies
    add_i = next(r["order_index"] for r in engine if r["strategy"] == "ADD_TESTS")
    ref_i = next(r["order_index"] for r in engine if r["strategy"] == "REFACTOR")
    assert add_i < ref_i
    assert all(r["classification"] == "RECOMMENDATION" for r in rows)
    assert all(r["component_qn"] == r["target"] for r in engine)
    assert "REWRITE" not in {r["strategy"] for r in rows}


def test_modernization_strategy_filter_and_evidence(client):
    _repo, run_id = _seed_plan(url="/tmp/mod-api-2")
    only = client.get(f"/runs/{run_id}/modernization?strategy=add_tests").json()
    assert only and all(r["strategy"] == "ADD_TESTS" for r in only)

    with session_scope() as s:
        evs = s.scalars(
            select(Evidence).where(
                Evidence.run_id == run_id, Evidence.stage == Stage.MODERNIZING
            )
        ).all()
        recs = s.scalars(
            select(ModernizationRecommendation).where(
                ModernizationRecommendation.run_id == run_id
            )
        ).all()
    assert len(evs) == len(recs) >= 2
    assert all(r.evidence_ids for r in recs)


def test_modernization_guards(client):
    assert client.get("/runs/nope/modernization").status_code == 404
    with session_scope() as s:
        repo = Repository(provider=ProviderKind.LOCAL, url="/tmp/mod-nosnap", name="x")
        s.add(repo)
        s.flush()
        run = AnalysisRun(repository_id=repo.id, mode=RunMode.ANALYSIS_ONLY,
                          state=RunState.RUNNING)
        s.add(run)
        s.flush()
        rid = run.id
    assert client.get(f"/runs/{rid}/modernization").status_code == 409
