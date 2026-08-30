"""Phase 3 acceptance contract (spec sections 4, 23, 53, 56).

FULL run on the fixture -> exact role histogram, the module DEPENDS_ON / TESTED_BY edge
sets, the central module, absence of cycles and layering violations, classified evidence,
and engine-version pinning.
"""

from __future__ import annotations

from sqlalchemy import func, select

from archon.core.artifacts import read_json
from archon.db.base import session_scope
from archon.db.models import (
    AnalysisArtifact,
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


def _run(test_repo) -> str:
    jobs = JobManager()
    with session_scope() as s:
        provider = provider_for(str(test_repo))
        ref = provider.parse(str(test_repo))
        repo = Repository(provider=provider.kind, url=ref.canonical_url, name=ref.name)
        s.add(repo)
        s.flush()
        rid = jobs.create_run_with_job(s, repository_id=repo.id, mode=RunMode.FULL).run_id
    w = Worker()
    while w.tick():
        pass
    return rid


def _edge_qns(session, sid, kind) -> set[tuple[str, str]]:
    edges = session.scalars(
        select(Dependency).where(Dependency.snapshot_id == sid, Dependency.kind == kind)
    ).all()
    out = set()
    for e in edges:
        src = session.get(Component, e.src_component_id).qualified_name
        dst = session.get(Component, e.dst_component_id).qualified_name
        out.add((src, dst))
    return out


def test_exact_architecture_for_fixture(test_repo):
    rid = _run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is Stage.RECONSTRUCTING_ARCHITECTURE
        sid = run.snapshot_id

        roles = {
            r: n
            for r, n in s.execute(
                select(Component.role, func.count(Component.id))
                .where(Component.snapshot_id == sid, Component.kind == ComponentKind.MODULE)
                .group_by(Component.role)
            ).all()
        }
        assert roles == {"domain": 3, "model": 1, "test": 3, "unknown": 1}

        # individual role calls
        def role_of(qn: str) -> str:
            return s.scalar(
                select(Component.role).where(
                    Component.snapshot_id == sid,
                    Component.qualified_name == qn,
                    Component.kind == ComponentKind.MODULE,
                )
            )

        assert role_of("legacy_shop.calculator") == "domain"
        assert role_of("legacy_shop.billing") == "domain"
        assert role_of("legacy_shop.inventory") == "domain"
        assert role_of("legacy_shop.orders") == "model"
        assert role_of("legacy_shop") == "unknown"
        assert role_of("tests.test_billing") == "test"

        assert _edge_qns(s, sid, DependencyKind.DEPENDS_ON) == {
            ("legacy_shop.billing", "legacy_shop.calculator"),
            ("legacy_shop.inventory", "legacy_shop.billing"),
            ("legacy_shop.orders", "legacy_shop.billing"),
            ("tests.test_billing", "legacy_shop.billing"),
            ("tests.test_calculator", "legacy_shop.calculator"),
        }
        assert _edge_qns(s, sid, DependencyKind.TESTED_BY) == {
            ("legacy_shop.billing", "tests.test_billing"),
            ("legacy_shop.calculator", "tests.test_calculator"),
        }


def test_central_module_and_no_cycles(test_repo):
    rid = _run(test_repo)
    with session_scope() as s:
        art = s.scalar(
            select(AnalysisArtifact).where(
                AnalysisArtifact.run_id == rid,
                AnalysisArtifact.kind == "architecture_graph",
            )
        )
        doc = read_json(art)
        assert doc["cycles"] == []
        assert doc["layering_violations"] == []

        mm = doc["module_metrics"]
        top = max(mm, key=lambda qn: mm[qn]["betweenness_centrality"])
        assert top == "legacy_shop.billing"
        assert mm["legacy_shop.billing"]["betweenness_centrality"] > 0
        assert mm["legacy_shop.calculator"]["fan_in"] == 2  # billing + test_calculator


def test_classified_evidence_and_version_pinning(test_repo):
    rid = _run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        arch_ev = [
            e for e in run.evidence
            if e.stage in (Stage.BUILDING_GRAPH, Stage.RECONSTRUCTING_ARCHITECTURE)
        ]
        assert arch_ev
        for e in arch_ev:
            assert e.classification in set(Classification)
            assert e.produced_by in {"graph.v1", "architecture.v1"}
        assert any(
            e.classification is Classification.FACT
            and "Reconstructed architecture: 8 modules" in e.summary
            for e in arch_ev
        )
        assert any(
            e.classification is Classification.FACT
            and "Module dependency graph: 8 modules, 5 DEPENDS_ON" in e.summary
            for e in arch_ev
        )
        for name in ("graph", "roles", "arch_metrics", "architecture"):
            assert run.engine_versions.get(name)


def test_rerun_reuses_cached_architecture(test_repo):
    r1 = _run(test_repo)
    with session_scope() as s:
        run1 = s.get(AnalysisRun, r1)
        sid = run1.snapshot_id
        job = JobManager().create_run_with_job(
            s, repository_id=run1.repository_id, mode=RunMode.FULL, config_hash="alt"
        )
        r2 = job.run_id
    w = Worker()
    while w.tick():
        pass
    with session_scope() as s:
        r2run = s.get(AnalysisRun, r2)
        assert r2run.snapshot_id == sid
        assert any("Reused cached architecture" in e.summary for e in r2run.evidence)
