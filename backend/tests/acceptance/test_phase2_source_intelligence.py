"""Phase 2 acceptance contract (spec sections 4, 22, 53, 56).

Runs the real pipeline in ANALYSIS_ONLY mode on the fixture repo and asserts the exact
source inventory, the key resolved relationships, entry-point detection, per-symbol
metrics, and that every conclusion is recorded as classified Evidence.
"""

from __future__ import annotations

from sqlalchemy import func, select

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
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
        job = jobs.create_run_with_job(s, repository_id=repo.id, mode=RunMode.ANALYSIS_ONLY)
        rid = job.run_id
    w = Worker()
    while w.tick():
        pass
    return rid


def test_exact_source_inventory_for_fixture(test_repo):
    rid = _run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        # ANALYSIS_ONLY now continues past source into the Phase 3 architecture stages
        assert run.last_completed_stage is terminal_stage("ANALYSIS_ONLY")
        assert any(e.stage is Stage.ANALYZING_SOURCE for e in run.evidence)
        sid = run.snapshot_id

        counts = {
            k.value: n
            for k, n in s.execute(
                select(Component.kind, func.count(Component.id))
                .where(Component.snapshot_id == sid)
                .group_by(Component.kind)
            ).all()
        }
        # 8 modules: legacy_shop(+ __init__), calculator, billing, inventory, orders,
        # tests(+ __init__), tests.test_calculator, tests.test_billing
        assert counts == {
            "FILE": 10,        # 8 .py files + pyproject.toml + requirements.txt
            "MODULE": 8,
            "CLASS": 2,        # Order, RushOrder
            "FUNCTION": 9,     # add, divide, line_total, unit_price, restock, reserve, 3 tests
            "METHOD": 4,       # Order.__init__/total/average, RushOrder.total
        }

        qns = {
            (c.kind.value, c.qualified_name)
            for c in s.scalars(select(Component).where(Component.snapshot_id == sid)).all()
        }
        assert ("FUNCTION", "legacy_shop.calculator.divide") in qns
        assert ("METHOD", "legacy_shop.orders.RushOrder.total") in qns
        assert ("MODULE", "tests.test_billing") in qns


def test_key_relationships_resolved(test_repo):
    rid = _run(test_repo)
    with session_scope() as s:
        sid = s.get(AnalysisRun, rid).snapshot_id

        def comp(qn: str, kind: ComponentKind) -> Component:
            return s.scalar(
                select(Component).where(
                    Component.snapshot_id == sid,
                    Component.qualified_name == qn,
                    Component.kind == kind,
                )
            )

        def has_edge(kind: DependencyKind, src: Component, dst: Component) -> bool:
            return s.scalar(
                select(func.count(Dependency.id)).where(
                    Dependency.snapshot_id == sid,
                    Dependency.kind == kind,
                    Dependency.src_component_id == src.id,
                    Dependency.dst_component_id == dst.id,
                    Dependency.resolved.is_(True),
                )
            ) >= 1

        billing = comp("legacy_shop.billing", ComponentKind.MODULE)
        calculator = comp("legacy_shop.calculator", ComponentKind.MODULE)
        inventory = comp("legacy_shop.inventory", ComponentKind.MODULE)
        unit_price = comp("legacy_shop.billing.unit_price", ComponentKind.FUNCTION)
        divide = comp("legacy_shop.calculator.divide", ComponentKind.FUNCTION)
        reserve = comp("legacy_shop.inventory.reserve", ComponentKind.FUNCTION)
        line_total = comp("legacy_shop.billing.line_total", ComponentKind.FUNCTION)
        order = comp("legacy_shop.orders.Order", ComponentKind.CLASS)
        rush = comp("legacy_shop.orders.RushOrder", ComponentKind.CLASS)

        assert has_edge(DependencyKind.IMPORTS, billing, calculator)
        assert has_edge(DependencyKind.IMPORTS, inventory, billing)
        assert has_edge(DependencyKind.CALLS, unit_price, divide)
        assert has_edge(DependencyKind.CALLS, reserve, line_total)
        assert has_edge(DependencyKind.INHERITS, rush, order)

        # CONTAINS backbone: module contains its functions/classes; class contains methods
        assert has_edge(DependencyKind.CONTAINS, billing, unit_price)
        assert has_edge(DependencyKind.CONTAINS, order, comp(
            "legacy_shop.orders.Order.total", ComponentKind.METHOD
        ))


def test_metrics_and_entrypoints(test_repo):
    rid = _run(test_repo)
    with session_scope() as s:
        sid = s.get(AnalysisRun, rid).snapshot_id
        divide = s.scalar(
            select(Component).where(
                Component.snapshot_id == sid,
                Component.qualified_name == "legacy_shop.calculator.divide",
            )
        )
        unit_price = s.scalar(
            select(Component).where(
                Component.snapshot_id == sid,
                Component.qualified_name == "legacy_shop.billing.unit_price",
            )
        )
        assert divide.metrics["complexity"] == 1
        assert unit_price.metrics["complexity"] == 2  # guards qty == 0
        assert unit_price.metrics["param_count"] == 2
        assert unit_price.metrics["args"] == ["total", "qty"]

        reserve = s.scalar(
            select(Component).where(
                Component.snapshot_id == sid,
                Component.qualified_name == "legacy_shop.inventory.reserve",
            )
        )
        assert "ValueError" in reserve.metrics["raises"]

        # the fixture declares no console scripts and has no __main__ guard
        entrypoints = s.scalar(
            select(func.count(Component.id)).where(
                Component.snapshot_id == sid, Component.is_entrypoint.is_(True)
            )
        )
        assert entrypoints == 0


def test_every_conclusion_is_classified_evidence(test_repo):
    rid = _run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        src_ev = [e for e in run.evidence if e.stage is Stage.ANALYZING_SOURCE]
        assert src_ev, "source stage produced no evidence"
        for e in src_ev:
            assert e.classification in set(Classification)
            assert e.produced_by == "source.v1"
        assert any(
            e.classification is Classification.FACT and "Extracted 8 Python modules" in e.summary
            for e in src_ev
        )
        # engine versions pinned for reproducibility
        assert run.engine_versions.get("source") == "source.v1"
        assert run.engine_versions.get("complexity") == "complexity.v1"


def test_rerun_reuses_cached_extraction(test_repo):
    r1 = _run(test_repo)
    with session_scope() as s:
        run1 = s.get(AnalysisRun, r1)
        sid = run1.snapshot_id
        before = s.scalar(select(func.count(Component.id)).where(Component.snapshot_id == sid))
        job = JobManager().create_run_with_job(
            s, repository_id=run1.repository_id, mode=RunMode.ANALYSIS_ONLY, config_hash="alt"
        )
        r2 = job.run_id
    w = Worker()
    while w.tick():
        pass
    with session_scope() as s:
        after = s.scalar(select(func.count(Component.id)).where(Component.snapshot_id == sid))
        assert after == before
        assert any(
            "Reused cached source analysis" in e.summary
            for e in s.get(AnalysisRun, r2).evidence
        )
