"""Structural test-gap candidate identification (spec sections 33-35) - a direct,
pipeline-free check of ``identify_untested_components`` against hand-built rows, since
the naive name-matching heuristic is easy to get subtly wrong."""

from __future__ import annotations

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    Component,
    Repository,
    RepositorySnapshot,
    TestCase,
)
from archon.domain.enums import ComponentKind, ProviderKind, TestCaseKind, TestCaseOrigin
from archon.testing.gaps import identify_untested_components


def _seed():
    with session_scope() as s:
        repo = Repository(provider=ProviderKind.LOCAL, url="file:///gap-test")
        s.add(repo)
        s.flush()
        snap = RepositorySnapshot(repository_id=repo.id, commit_sha="deadbeef")
        s.add(snap)
        s.flush()
        run = AnalysisRun(repository_id=repo.id, snapshot_id=snap.id)
        s.add(run)
        s.flush()

        tested = Component(
            snapshot_id=snap.id, kind=ComponentKind.FUNCTION, name="add",
            qualified_name="pkg.mod.add", path="pkg/mod.py",
        )
        untested = Component(
            snapshot_id=snap.id, kind=ComponentKind.FUNCTION, name="reserve",
            qualified_name="pkg.mod.reserve", path="pkg/mod.py",
        )
        is_test = Component(
            snapshot_id=snap.id, kind=ComponentKind.FUNCTION, name="test_add",
            qualified_name="tests.test_mod.test_add", path="tests/test_mod.py", is_test=True,
        )
        s.add_all([tested, untested, is_test])
        s.flush()

        s.add(
            TestCase(
                run_id=run.id, snapshot_id=snap.id, component_id=is_test.id,
                kind=TestCaseKind.EXISTING, path="tests/test_mod.py", name="tests.test_mod.test_add",
                origin=TestCaseOrigin.DISCOVERED, validated=True, produced_by="test_discovery.v1",
            )
        )
        s.flush()
        return run.id, snap.id, tested.id, untested.id


def test_identify_untested_components_excludes_naively_matched_functions():
    run_id, snap_id, tested_id, untested_id = _seed()
    with session_scope() as s:
        run = s.get(AnalysisRun, run_id)
        snap = s.get(RepositorySnapshot, snap_id)
        candidates = identify_untested_components(s, run, snap)
        candidate_ids = {c.id for c in candidates}
        assert untested_id in candidate_ids
        assert tested_id not in candidate_ids


def test_identify_untested_components_respects_limit():
    run_id, snap_id, _, _ = _seed()
    with session_scope() as s:
        run = s.get(AnalysisRun, run_id)
        snap = s.get(RepositorySnapshot, snap_id)
        assert len(identify_untested_components(s, run, snap, limit=1)) == 1
