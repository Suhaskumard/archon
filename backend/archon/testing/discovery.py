"""Existing-test discovery (spec section 33) - the ``ANALYZING_TESTS`` stage.

Pure discovery of what Phase 2's source extractor already found - not characterization,
not AI generation (Phase 8). Phase 2 only sets ``is_test`` on the MODULE/FILE component
for a test file, not on the individual FUNCTION/METHOD components inside it, so a test
function is identified by: its owning module is flagged ``is_test``, and its own name
looks like a test (``test_`` prefix). Cheap enough to always recompute, like
``understanding_run.py`` - no snapshot-level caching.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.core.logging import get_logger
from archon.db.models import AnalysisRun, Component, Evidence, RepositorySnapshot, TestCase
from archon.domain.enums import Classification, ComponentKind, Stage, TestCaseKind, TestCaseOrigin

log = get_logger("archon.testing.discovery")

TEST_DISCOVERY_VERSION = "test_discovery.v1"


@dataclass
class TestDiscoverySummary:
    discovered: int

    def as_dict(self) -> dict:
        return {"discovered": self.discovered}


def discover_existing_tests(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
) -> TestDiscoverySummary:
    test_module_paths = set(
        session.scalars(
            select(Component.path).where(
                Component.snapshot_id == snapshot.id,
                Component.is_test.is_(True),
                Component.kind == ComponentKind.MODULE,
            )
        ).all()
    )
    comps = (
        session.scalars(
            select(Component).where(
                Component.snapshot_id == snapshot.id,
                Component.kind.in_([ComponentKind.FUNCTION, ComponentKind.METHOD]),
                Component.name.startswith("test_"),
                Component.path.in_(test_module_paths),
            )
        ).all()
        if test_module_paths
        else []
    )

    for c in comps:
        session.add(
            TestCase(
                run_id=run.id, snapshot_id=snapshot.id, component_id=c.id,
                kind=TestCaseKind.EXISTING, path=c.path, name=c.qualified_name,
                origin=TestCaseOrigin.DISCOVERED, validated=True,
                produced_by=TEST_DISCOVERY_VERSION,
            )
        )
    session.flush()

    session.add(
        Evidence(
            run_id=run.id, stage=Stage.ANALYZING_TESTS, classification=Classification.FACT,
            summary=f"Discovered {len(comps)} existing test(s)",
            produced_by=TEST_DISCOVERY_VERSION, confidence=1.0,
        )
    )
    session.flush()
    log.info("existing tests discovered", extra={"extra_fields": {"run_id": run.id, "count": len(comps)}})
    return TestDiscoverySummary(discovered=len(comps))
