"""Test-gap analysis (spec sections 33-35).

Split across two data sources because of the fixed stage order
(``ANALYZING_TESTS -> CHARACTERIZING -> GENERATING_TESTS -> EXECUTING``):

* ``identify_untested_components`` - a *structural* heuristic (no coverage needed),
  used by ``ANALYZING_TESTS``/``CHARACTERIZING``/``GENERATING_TESTS`` to pick targets
  before this run's own ``coverage.xml`` exists.
* ``analyze_test_gaps`` - the real, coverage-informed pass, run from ``EXECUTING``
  *after* the combined suite (existing + characterization + AI-generated tests) has
  produced this run's ``coverage.xml``. Prioritized by this run's already-persisted
  ``LegacyDNA.legacy_risk_score`` / ``ChangeAssessment.safety_score`` (both computed
  earlier in the same run by Phases 5/6). Historical-failures prioritization has no
  data until Phase 9 - weighted 0 and recorded as an explicit, documented omission in
  ``factor_breakdown``, never silently dropped.

Only two of the five declared ``TestGapKind`` values are actually distinguished by this
engine (``UNTESTED_FUNCTION`` for 0% coverage, ``MISSING_EDGE_CASE`` for partial
coverage) - the rest of the vocabulary is declared for a future, more precise engine,
matching the project's "declare the full vocabulary, populate the tractable subset"
convention (see ``TestCaseKind``/``ExecutionKind``).

Retrofitting real coverage into ``LegacyDNA.coverage``/``ChangeAssessment.coverage``
(still the documented ``TESTED_BY``-edge proxy) is a deliberate scope cut: those
engines' acceptance tests pin exact numeric scores from Phases 5-6, and this module's
own ``coverage_pct`` already reads the real data directly - see
``docs/PHASE_8_COMPLETION.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    ChangeAssessment,
    Component,
    Evidence,
    LegacyDNA,
    RepositorySnapshot,
    TestCase,
    TestGap,
)
from archon.domain.enums import Classification, ComponentKind, Stage, TestGapKind, TestGapPriority
from archon.testing.coverage import component_coverage_pct, parse_coverage_xml

log = get_logger("archon.testing.gaps")

TEST_GAP_VERSION = "test_gap_analysis.v1"

_TARGET_KINDS = (ComponentKind.FUNCTION, ComponentKind.METHOD)
_PRIORITY_THRESHOLDS = {"LOW": 25.0, "MEDIUM": 50.0, "HIGH": 75.0}
_WEIGHTS = {"legacy_risk": 0.4, "change_danger": 0.4, "coverage_gap": 0.2}
_MAX_CRITICAL_EVIDENCE = 15


def _has_naive_test(component: Component, discovered_test_names: set[str]) -> bool:
    needle = f"test_{component.name}"
    return any(needle in name for name in discovered_test_names)


def identify_untested_components(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, *, limit: int | None = None
) -> list[Component]:
    """Structural (no-coverage) candidate list: FUNCTION/METHOD components with no
    discovered test whose name naively matches them. Cheap enough to recompute in every
    stage that needs it - no cross-stage state."""
    comps = session.scalars(
        select(Component).where(
            Component.snapshot_id == snapshot.id,
            Component.kind.in_(_TARGET_KINDS),
            Component.is_test.is_(False),
        )
    ).all()
    discovered_names = set(
        session.scalars(select(TestCase.name).where(TestCase.run_id == run.id)).all()
    )
    candidates = [c for c in comps if not _has_naive_test(c, discovered_names)]
    candidates.sort(key=lambda c: c.qualified_name)
    return candidates[:limit] if limit else candidates


def _priority(score: float) -> str:
    t = _PRIORITY_THRESHOLDS
    if score >= t["HIGH"]:
        return TestGapPriority.CRITICAL.value
    if score >= t["MEDIUM"]:
        return TestGapPriority.HIGH.value
    if score >= t["LOW"]:
        return TestGapPriority.MEDIUM.value
    return TestGapPriority.LOW.value


@dataclass
class TestGapSummary:
    found: int
    by_priority: dict[str, int]

    def as_dict(self) -> dict:
        return {"found": self.found, "by_priority": self.by_priority}


def analyze_test_gaps(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, coverage_xml_text: str
) -> TestGapSummary:
    session.execute(delete(TestGap).where(TestGap.run_id == run.id))

    file_coverage = parse_coverage_xml(coverage_xml_text)
    comps = session.scalars(
        select(Component).where(
            Component.snapshot_id == snapshot.id,
            Component.kind.in_(_TARGET_KINDS),
            Component.is_test.is_(False),
        )
    ).all()
    legacy_by_id = {
        r.component_id: r
        for r in session.scalars(select(LegacyDNA).where(LegacyDNA.run_id == run.id)).all()
    }
    change_by_id = {
        r.component_id: r
        for r in session.scalars(select(ChangeAssessment).where(ChangeAssessment.run_id == run.id)).all()
    }

    found = 0
    by_priority: dict[str, int] = {}

    for c in comps:
        coverage_pct = component_coverage_pct(c, file_coverage)
        if coverage_pct >= 1.0:
            continue

        legacy = legacy_by_id.get(c.id)
        change = change_by_id.get(c.id)
        legacy_risk_score = legacy.legacy_risk_score if legacy else None
        change_safety_score = change.safety_score if change else None

        legacy_norm = (legacy_risk_score / 100.0) if legacy_risk_score is not None else 0.0
        change_danger_norm = (1.0 - change_safety_score / 100.0) if change_safety_score is not None else 0.0
        coverage_gap_norm = 1.0 - coverage_pct

        priority_score = round(
            100.0 * (
                _WEIGHTS["legacy_risk"] * legacy_norm
                + _WEIGHTS["change_danger"] * change_danger_norm
                + _WEIGHTS["coverage_gap"] * coverage_gap_norm
            ),
            2,
        )
        confidence = round(
            sum(1 for v in (legacy_risk_score, change_safety_score) if v is not None) / 2.0, 4
        )
        kind = TestGapKind.UNTESTED_FUNCTION if coverage_pct == 0.0 else TestGapKind.MISSING_EDGE_CASE

        session.add(
            TestGap(
                run_id=run.id, snapshot_id=snapshot.id, component_id=c.id, kind=kind,
                coverage_pct=coverage_pct, legacy_risk_score=legacy_risk_score,
                change_safety_score=change_safety_score, priority_score=priority_score,
                priority=_priority(priority_score), confidence=confidence,
                factor_breakdown={
                    "legacy_risk_norm": legacy_norm,
                    "change_danger_norm": change_danger_norm,
                    "coverage_gap_norm": coverage_gap_norm,
                    "weights": _WEIGHTS,
                    "historical_failures": {"weight": 0.0, "reason": "no data until Phase 9"},
                },
                evidence_ids=None, produced_by=TEST_GAP_VERSION,
            )
        )
        found += 1
        by_priority[kind.value + ":" + _priority(priority_score)] = (
            by_priority.get(kind.value + ":" + _priority(priority_score), 0) + 1
        )

    session.flush()
    cat_str = ", ".join(f"{k}={v}" for k, v in sorted(by_priority.items()))
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.EXECUTING, classification=Classification.INFERENCE,
            summary=f"Test-gap analysis found {found} gap(s): {cat_str}" if found else "No test gaps found",
            produced_by=TEST_GAP_VERSION, confidence=1.0, refs={"by_priority": by_priority},
        )
    )
    critical = session.scalars(
        select(TestGap).where(TestGap.run_id == run.id, TestGap.priority == "CRITICAL")
    ).all()
    for row in critical[:_MAX_CRITICAL_EVIDENCE]:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.EXECUTING, classification=Classification.HYPOTHESIS,
                summary=f"Critical test gap (priority_score={row.priority_score}) for component {row.component_id}",
                detail=f"coverage_pct={row.coverage_pct} kind={row.kind}",
                produced_by=TEST_GAP_VERSION, confidence=row.confidence,
            )
        )
    session.flush()
    log.info(
        "test gaps analyzed",
        extra={"extra_fields": {"run_id": run.id, "found": found, "by_priority": by_priority}},
    )
    return TestGapSummary(found=found, by_priority=by_priority)
