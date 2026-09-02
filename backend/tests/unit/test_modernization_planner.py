"""Phase 12 - modernization planner (spec section 46).

Exercises the deterministic pieces against hand-built analysis rows: the
``_op_modernization_recommendation`` finding->strategy mapping, ``assemble_targets``
candidate filtering, and ``compute_safe_order`` (dependencies first, add_tests before
structural strategies, deterministic).
"""

from __future__ import annotations

from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    ChangeAssessment,
    Component,
    Dependency,
    LegacyDNA,
    ModernizationRecommendation,
    Repository,
    RepositorySnapshot,
    TechnicalDebtFinding,
)
from archon.domain.ai_schemas import ModernizationItem
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
from archon.modernization.planner import (
    assemble_targets,
    compute_safe_order,
    generate_modernization_plan,
)
from archon.providers.ai.mock import MockAIProvider

# --- mock op ---------------------------------------------------------------------------


def test_mock_maps_untested_high_risk_to_add_tests():
    out = MockAIProvider()._op_modernization_recommendation({
        "targets": [{
            "qualified_name": "pkg.risky", "legacy_category": "HIGH", "coverage": 0.0,
            "complexity": 3, "coupling": 2, "debt_categories": [], "in_cycle": False,
        }],
        "known_refs": {"component": {"pkg.risky"}},
    })
    strategies = {r["strategy"] for r in out["recommendations"]}
    assert strategies == {"add_tests"}
    assert out["classification"] == "RECOMMENDATION"


def test_mock_never_rewrites_when_a_cheaper_option_fires():
    out = MockAIProvider()._op_modernization_recommendation({
        "targets": [{
            "qualified_name": "pkg.crit", "legacy_category": "CRITICAL", "coverage": 0.0,
            "complexity": 20, "coupling": 12,
            "debt_categories": ["BROAD_EXCEPT", "CIRCULAR_DEPENDENCY"], "in_cycle": True,
        }],
        "known_refs": {"component": {"pkg.crit"}},
    })
    strategies = {r["strategy"] for r in out["recommendations"]}
    assert "rewrite" not in strategies
    assert {"add_tests", "extract_dependency", "refactor"} <= strategies


def test_mock_empty_targets_is_unknown():
    out = MockAIProvider()._op_modernization_recommendation({"targets": []})
    assert out["recommendations"] == []
    assert out["confidence"] == "UNKNOWN"


# --- planner against real rows -------------------------------------------------------


def _module(session, snap_id, qn):
    c = Component(
        snapshot_id=snap_id, kind=ComponentKind.MODULE, name=qn.split(".")[-1],
        qualified_name=qn, path=qn.replace(".", "/") + ".py",
    )
    session.add(c)
    session.flush()
    return c


def _seed(session, *, chain: list[str], risky: dict[str, dict]):
    """`chain[i]` imports `chain[i+1]`; `risky` maps qn -> scoring spec."""
    repo = Repository(provider=ProviderKind.LOCAL, url=f"/tmp/{id(session)}", name="m")
    session.add(repo)
    session.flush()
    snap = RepositorySnapshot(repository_id=repo.id, commit_sha="a" * 40)
    session.add(snap)
    session.flush()
    run = AnalysisRun(
        repository_id=repo.id, snapshot_id=snap.id, mode=RunMode.ANALYSIS_ONLY,
        state=RunState.COMPLETED, last_completed_stage=Stage.MODERNIZING,
    )
    session.add(run)
    session.flush()

    comps = {qn: _module(session, snap.id, qn) for qn in chain}
    for a, b in zip(chain, chain[1:], strict=False):
        session.add(Dependency(
            snapshot_id=snap.id, src_component_id=comps[a].id, dst_component_id=comps[b].id,
            kind=DependencyKind.IMPORTS, target_name=b,
        ))
    for qn, spec in risky.items():
        c = comps[qn]
        session.add(LegacyDNA(
            run_id=run.id, snapshot_id=snap.id, component_id=c.id,
            coverage=spec.get("coverage", 0.0), complexity=spec.get("complexity", 12),
            coupling=spec.get("coupling", 9),
            legacy_risk_score=spec.get("risk", 80.0), category=spec.get("category", "HIGH"),
            confidence=0.9, produced_by="legacy_risk.v1",
        ))
        session.add(ChangeAssessment(
            run_id=run.id, snapshot_id=snap.id, component_id=c.id,
            engine_version="change_safety.v1", safety_score=spec.get("safety", 40.0),
            risk_category=spec.get("safety_cat", "RISKY"), confidence=0.9,
            produced_by="change_safety.v1",
        ))
        for cat in spec.get("debt", []):
            session.add(TechnicalDebtFinding(
                run_id=run.id, snapshot_id=snap.id, component_id=c.id, category=cat,
                location=f"{qn.replace('.', '/')}.py:1", severity=TechDebtSeverity.MEDIUM,
                confidence=0.8, produced_by="tech_debt.v1",
            ))
    session.flush()
    return run.id, snap.id


def test_assemble_targets_filters_clean_modules():
    with session_scope() as s:
        run_id, _snap = _seed(
            s, chain=["pkg.a", "pkg.b", "pkg.clean"],
            risky={
                "pkg.a": {"category": "HIGH", "debt": [TechDebtCategory.LONG_FUNCTION]},
                "pkg.b": {"category": "MODERATE"},
                "pkg.clean": {"category": "LOW", "risk": 5.0, "coverage": 0.9,
                              "complexity": 1, "coupling": 0, "safety": 95.0,
                              "safety_cat": "SAFE"},
            },
        )
        run = s.get(AnalysisRun, run_id)
        snap = s.get(RepositorySnapshot, run.snapshot_id)
        qns = {t["qualified_name"] for t in assemble_targets(s, run, snap)}
    assert "pkg.a" in qns and "pkg.b" in qns
    assert "pkg.clean" not in qns


def test_compute_safe_order_dependencies_and_strategy():
    items = [
        ModernizationItem(target="pkg.a", strategy="refactor"),
        ModernizationItem(target="pkg.a", strategy="add_tests"),
        ModernizationItem(target="pkg.c", strategy="add_tests"),
        ModernizationItem(target="pkg.b", strategy="refactor"),
    ]
    targets = [
        {"qualified_name": "pkg.a", "change_safety_score": 40.0, "legacy_risk_score": 80.0},
        {"qualified_name": "pkg.b", "change_safety_score": 50.0, "legacy_risk_score": 70.0},
        {"qualified_name": "pkg.c", "change_safety_score": 60.0, "legacy_risk_score": 60.0},
    ]
    with session_scope() as s:
        _run_id, snap_id = _seed(
            s, chain=["pkg.a", "pkg.b", "pkg.c"],
            risky={"pkg.a": {}, "pkg.b": {}, "pkg.c": {}},
        )
        snap = s.get(RepositorySnapshot, snap_id)
        ordered = compute_safe_order(s, snap, items, targets)

    seq = [(e["item"].target, e["item"].strategy) for e in ordered]
    # deepest dependency (pkg.c) first, root dependent (pkg.a) last
    assert seq.index(("pkg.c", "add_tests")) < seq.index(("pkg.b", "refactor"))
    assert seq.index(("pkg.b", "refactor")) < seq.index(("pkg.a", "add_tests"))
    # add_tests before refactor for the same target
    assert seq.index(("pkg.a", "add_tests")) < seq.index(("pkg.a", "refactor"))
    assert [e["order_index"] for e in ordered] == list(range(len(ordered)))
    # deterministic
    with session_scope() as s:
        snap = s.get(RepositorySnapshot, snap_id)
        again = compute_safe_order(s, snap, items, targets)
    assert [(e["item"].target, e["item"].strategy) for e in again] == seq


def test_generate_plan_end_to_end_add_tests_before_refactor():
    with session_scope() as s:
        run_id, _snap = _seed(
            s, chain=["pkg.top", "pkg.mid", "pkg.leaf"],
            risky={
                "pkg.top": {"category": "HIGH", "coverage": 0.0,
                            "debt": [TechDebtCategory.LONG_FUNCTION]},
                "pkg.mid": {"category": "MODERATE", "coverage": 0.2},
                "pkg.leaf": {"category": "CRITICAL", "coverage": 0.0, "complexity": 25,
                             "coupling": 14, "debt": [TechDebtCategory.BROAD_EXCEPT]},
            },
        )
        summary = generate_modernization_plan(
            s, s.get(AnalysisRun, run_id), s.get(RepositorySnapshot,
                                                s.get(AnalysisRun, run_id).snapshot_id)
        )
        rows = s.scalars(
            select(ModernizationRecommendation)
            .where(ModernizationRecommendation.run_id == run_id)
            .order_by(ModernizationRecommendation.order_index)
        ).all()
        by = [(r.target, r.strategy.value, r.order_index) for r in rows]

    assert summary.recommended == len(rows) > 0
    assert "REWRITE" not in {st for _t, st, _i in by}
    top_add = next(i for t, st, i in by if t == "pkg.top" and st == "ADD_TESTS")
    top_ref = next(i for t, st, i in by if t == "pkg.top" and st == "REFACTOR")
    assert top_add < top_ref
    # leaf (deepest dependency) is ordered before top (its dependent)
    leaf_first = min(i for t, _st, i in by if t == "pkg.leaf")
    top_first = min(i for t, _st, i in by if t == "pkg.top")
    assert leaf_first < top_first
