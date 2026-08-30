"""BUILDING_GRAPH + RECONSTRUCTING_ARCHITECTURE stages through the pipeline (spec section 23)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import func, select

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


def _full_run(test_repo) -> str:
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


def test_pipeline_reconstructs_architecture(test_repo):
    rid = _full_run(test_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is Stage.RECONSTRUCTING_ARCHITECTURE
        sid = run.snapshot_id

        # every component has a role (module role mirrored onto descendants)
        no_role = s.scalar(
            select(func.count(Component.id)).where(
                Component.snapshot_id == sid, Component.role.is_(None)
            )
        )
        assert no_role == 0

        # module roles for the fixture
        roles = {
            r: n
            for r, n in s.execute(
                select(Component.role, func.count(Component.id))
                .where(Component.snapshot_id == sid, Component.kind == ComponentKind.MODULE)
                .group_by(Component.role)
            ).all()
        }
        assert roles == {"domain": 3, "model": 1, "test": 3, "unknown": 1}

        # derived edges
        depends_on = s.scalar(
            select(func.count(Dependency.id)).where(
                Dependency.snapshot_id == sid, Dependency.kind == DependencyKind.DEPENDS_ON
            )
        )
        tested_by = s.scalar(
            select(func.count(Dependency.id)).where(
                Dependency.snapshot_id == sid, Dependency.kind == DependencyKind.TESTED_BY
            )
        )
        assert depends_on == 5
        assert tested_by == 2

        # module architecture metrics persisted
        billing = s.scalar(
            select(Component).where(
                Component.snapshot_id == sid,
                Component.qualified_name == "legacy_shop.billing",
                Component.kind == ComponentKind.MODULE,
            )
        )
        arch = billing.metrics["architecture"]
        assert arch["fan_in"] == 3 and arch["fan_out"] == 1
        assert arch["role"] == "domain"
        assert set(arch["dependents"]) == {
            "legacy_shop.inventory", "legacy_shop.orders", "tests.test_billing"
        }

        # graph artifact on disk with a matching content hash
        art = s.scalar(
            select(AnalysisArtifact).where(
                AnalysisArtifact.run_id == rid,
                AnalysisArtifact.kind == "architecture_graph",
            )
        )
        assert art is not None and art.storage == "fs"
        data = Path(art.ref).read_bytes()
        assert hashlib.sha256(data).hexdigest() == art.sha256

        # classified evidence
        stages = {e.stage for e in run.evidence}
        assert Stage.BUILDING_GRAPH in stages and Stage.RECONSTRUCTING_ARCHITECTURE in stages
        assert any(
            "Reconstructed architecture" in e.summary and e.produced_by == "architecture.v1"
            for e in run.evidence
        )
        assert run.engine_versions.get("roles") == "roles.v1"
        assert run.engine_versions.get("architecture") == "architecture.v1"


def test_no_cycles_or_layering_violations_for_fixture(test_repo):
    rid = _full_run(test_repo)
    with session_scope() as s:
        from archon.core.artifacts import read_json

        art = s.scalar(
            select(AnalysisArtifact).where(
                AnalysisArtifact.run_id == rid,
                AnalysisArtifact.kind == "architecture_graph",
            )
        )
        doc = read_json(art)
        assert doc["cycles"] == []
        assert doc["layering_violations"] == []
        assert doc["schema"] == "archon.graph.v1"
        assert doc["roles"]["legacy_shop.orders"] == "model"


def test_architecture_is_cached_per_snapshot(test_repo):
    r1 = _full_run(test_repo)
    with session_scope() as s:
        run1 = s.get(AnalysisRun, r1)
        repo_id, sid = run1.repository_id, run1.snapshot_id
        billing_before = s.scalar(
            select(Component).where(
                Component.snapshot_id == sid,
                Component.qualified_name == "legacy_shop.billing",
                Component.kind == ComponentKind.MODULE,
            )
        ).role
        job = JobManager().create_run_with_job(
            s, repository_id=repo_id, mode=RunMode.FULL, config_hash="v2"
        )
        r2 = job.run_id
    w = Worker()
    while w.tick():
        pass
    with session_scope() as s:
        r2run = s.get(AnalysisRun, r2)
        assert r2run.state is RunState.COMPLETED
        assert r2run.snapshot_id == sid
        assert any(
            "Reused cached architecture" in e.summary for e in r2run.evidence
        )
        billing_after = s.scalar(
            select(Component).where(
                Component.snapshot_id == sid,
                Component.qualified_name == "legacy_shop.billing",
                Component.kind == ComponentKind.MODULE,
            )
        ).role
        assert billing_after == billing_before
