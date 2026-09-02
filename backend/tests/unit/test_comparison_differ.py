"""Phase 11 - repository comparison differ (spec section 45).

Exercises ``compute_comparison`` against hand-built analysis rows for two runs of
one repository: added/removed modules and dependencies, per-component legacy-risk /
change-safety / coverage deltas, category regressions, tech-debt add/resolve, and
antisymmetry when base and head are swapped.
"""

from __future__ import annotations

from archon.comparison import compute_comparison
from archon.comparison.differ import COMPARISON_VERSION
from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    ChangeAssessment,
    Component,
    Dependency,
    LegacyDNA,
    Repository,
    RepositorySnapshot,
    RiskAssessment,
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

_ENGINE = "legacy_risk.v1"


def _make_run(session, repo_id: str, sha: str, modules: dict[str, dict]) -> str:
    snap = RepositorySnapshot(repository_id=repo_id, commit_sha=sha)
    session.add(snap)
    session.flush()
    run = AnalysisRun(
        repository_id=repo_id, snapshot_id=snap.id, mode=RunMode.ANALYSIS_ONLY,
        state=RunState.COMPLETED, last_completed_stage=Stage.ASSESSING_CHANGE_SAFETY,
    )
    session.add(run)
    session.flush()

    comps: dict[str, Component] = {}
    for qn, spec in modules.items():
        c = Component(
            snapshot_id=snap.id, kind=ComponentKind.MODULE, name=qn.split(".")[-1],
            qualified_name=qn, path=qn.replace(".", "/") + ".py", role=spec.get("role"),
        )
        session.add(c)
        session.flush()
        comps[qn] = c
        session.add(LegacyDNA(
            run_id=run.id, snapshot_id=snap.id, component_id=c.id,
            coverage=spec["coverage"], debt_score=spec.get("debt_score", 0.0),
            legacy_risk_score=spec["risk"], category=spec["risk_cat"],
            confidence=0.9, produced_by=_ENGINE,
        ))
        session.add(RiskAssessment(
            run_id=run.id, snapshot_id=snap.id, component_id=c.id, engine_version=_ENGINE,
            score=spec["risk"], category=spec["risk_cat"], confidence=0.9, produced_by=_ENGINE,
        ))
        session.add(ChangeAssessment(
            run_id=run.id, snapshot_id=snap.id, component_id=c.id, engine_version="change_safety.v1",
            safety_score=spec["safety"], risk_category=spec["safety_cat"],
            confidence=0.9, produced_by="change_safety.v1",
        ))
        for cat, loc, sev in spec.get("debt", []):
            session.add(TechnicalDebtFinding(
                run_id=run.id, snapshot_id=snap.id, component_id=c.id, category=cat,
                location=loc, severity=sev, confidence=0.8, produced_by="tech_debt.v1",
            ))

    for src_qn, dst_qn in [
        (a, b) for a in modules for b in modules.get(a, {}).get("imports", [])
    ]:
        session.add(Dependency(
            snapshot_id=snap.id, src_component_id=comps[src_qn].id,
            dst_component_id=comps[dst_qn].id, kind=DependencyKind.IMPORTS, target_name=dst_qn,
        ))
    session.flush()
    return run.id


def _base_head():
    """base: 2 modules; head: adds `shop.inventory`, billing risk up + coverage down,
    resolves one debt finding, adds one import edge."""
    with session_scope() as s:
        repo = Repository(provider=ProviderKind.LOCAL, url="/tmp/x", name="x")
        s.add(repo)
        s.flush()
        base = _make_run(s, repo.id, "a" * 40, {
            "shop.calculator": {
                "risk": 10.0, "risk_cat": "LOW", "coverage": 0.9, "safety": 90.0,
                "safety_cat": "SAFE", "role": "util",
            },
            "shop.billing": {
                "risk": 40.0, "risk_cat": "MODERATE", "coverage": 0.8, "safety": 70.0,
                "safety_cat": "CAUTION", "imports": ["shop.calculator"],
                "debt": [(TechDebtCategory.BROAD_EXCEPT, "shop/billing.py:12", TechDebtSeverity.LOW)],
            },
        })
        head = _make_run(s, repo.id, "b" * 40, {
            "shop.calculator": {
                "risk": 10.0, "risk_cat": "LOW", "coverage": 0.9, "safety": 90.0,
                "safety_cat": "SAFE", "role": "util",
            },
            "shop.billing": {
                "risk": 75.0, "risk_cat": "HIGH", "coverage": 0.55, "safety": 45.0,
                "safety_cat": "RISKY", "imports": ["shop.calculator", "shop.inventory"],
            },
            "shop.inventory": {
                "risk": 30.0, "risk_cat": "MODERATE", "coverage": 0.6, "safety": 65.0,
                "safety_cat": "CAUTION", "imports": ["shop.billing"],
            },
        })
        return repo.id, base, head


def test_added_module_detected():
    _repo, base, head = _base_head()
    with session_scope() as s:
        report = compute_comparison(s, s.get(AnalysisRun, base), s.get(AnalysisRun, head))
    assert report["produced_by"] == COMPARISON_VERSION
    assert report["architecture"]["modules_added"] == ["shop.inventory"]
    assert report["architecture"]["modules_removed"] == []
    assert report["summary"]["modules_added"] == 1


def test_dependency_edges_diffed():
    _repo, base, head = _base_head()
    with session_scope() as s:
        report = compute_comparison(s, s.get(AnalysisRun, base), s.get(AnalysisRun, head))
    added = report["dependencies"]["edges_added"]
    assert any("shop.billing" in e and "shop.inventory" in e for e in added)
    assert report["dependencies"]["edges_removed"] == []


def test_legacy_risk_delta_and_regression():
    _repo, base, head = _base_head()
    with session_scope() as s:
        report = compute_comparison(s, s.get(AnalysisRun, base), s.get(AnalysisRun, head))
    dna = report["legacy_dna"]
    billing = next(c for c in dna["changed"] if c["qualified_name"] == "shop.billing")
    assert billing["delta"] == 35.0
    assert billing["base_category"] == "MODERATE" and billing["head_category"] == "HIGH"
    assert "shop.billing" in dna["risk_category_regressions"]
    assert dna["mean_legacy_risk_delta"] > 0


def test_change_safety_regression_detected():
    _repo, base, head = _base_head()
    with session_scope() as s:
        report = compute_comparison(s, s.get(AnalysisRun, base), s.get(AnalysisRun, head))
    cs = report["change_safety"]
    assert "shop.billing" in cs["change_safety_regressions"]
    assert cs["mean_change_safety_delta"] < 0


def test_coverage_marked_proxy_and_billing_worse():
    _repo, base, head = _base_head()
    with session_scope() as s:
        report = compute_comparison(s, s.get(AnalysisRun, base), s.get(AnalysisRun, head))
    cov = report["coverage"]
    assert cov["is_proxy"] is True
    assert "shop.billing" in cov["components_worse"]


def test_tech_debt_resolved_tracked():
    _repo, base, head = _base_head()
    with session_scope() as s:
        report = compute_comparison(s, s.get(AnalysisRun, base), s.get(AnalysisRun, head))
    debt = report["technical_debt"]
    assert len(debt["findings_resolved"]) == 1
    assert debt["findings_resolved"][0]["qualified_name"] == "shop.billing"
    assert debt["findings_added"] == []


def test_antisymmetric_when_swapped():
    _repo, base, head = _base_head()
    with session_scope() as s:
        fwd = compute_comparison(s, s.get(AnalysisRun, base), s.get(AnalysisRun, head))
        rev = compute_comparison(s, s.get(AnalysisRun, head), s.get(AnalysisRun, base))
    assert rev["architecture"]["modules_removed"] == fwd["architecture"]["modules_added"]
    assert rev["legacy_dna"]["mean_legacy_risk_delta"] == -fwd["legacy_dna"]["mean_legacy_risk_delta"]
    assert rev["change_safety"]["change_safety_regressions"] == []  # head->base is an improvement
