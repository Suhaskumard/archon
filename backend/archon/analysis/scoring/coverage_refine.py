"""Re-score Legacy DNA / Hotspot with *measured* coverage after ``EXECUTING`` (Phase 16).

``BUILDING_LEGACY_DNA`` / ``SCORING_HOTSPOTS`` run before the sandbox produces this run's
``coverage.xml``, so they score with the presence proxy (0.5 if the module has a test
file, else 0.0). Once ``EXECUTING`` has real per-line coverage, ``refine_scores_with_
measured_coverage`` recomputes the affected rows: ``coverage`` becomes the measured
fraction and ``coverage_is_proxy`` flips to ``False`` (which *raises* confidence, since
coverage-gap is no longer a defaulted signal). ``backfill_failure_counts`` runs one stage
later (``DETECTING_FAILURES``, once ``Failure`` rows exist) and fills
``LegacyDNA.failure_count`` - recorded, not scored. In ``ANALYSIS_ONLY`` mode neither
runs and the proxy stands.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.analysis.scoring.hotspot import HotspotSignals, hotspot_score
from archon.analysis.scoring.legacy_risk import (
    LEGACY_RISK_VERSION,
    LegacyRiskSignals,
    legacy_risk_score,
)
from archon.analysis.scoring.thresholds import DEBT_SCORE_MAX, SEVERITY_WEIGHT
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Component,
    Evidence,
    Failure,
    Hotspot,
    LegacyDNA,
    RepositorySnapshot,
    RiskAssessment,
    TechnicalDebtFinding,
)
from archon.domain.enums import Classification, Stage
from archon.testing.coverage import component_coverage_pct, parse_coverage_xml

log = get_logger("archon.scoring.coverage_refine")

COVERAGE_REFINE_VERSION = "coverage_refine.v1"


@dataclass
class RefineSummary:
    refined: int

    def as_dict(self) -> dict:
        return {"coverage_refined": self.refined}


def _failure_count_by_component(session: Session, run_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in session.scalars(select(Failure).where(Failure.run_id == run_id)).all():
        hit: set[str] = set()
        for frame in f.parsed_frames or []:
            cid = frame.get("component_id")
            if cid:
                hit.add(cid)
        for cid in hit:  # one failure counts once per component it touches
            counts[cid] = counts.get(cid, 0) + 1
    return counts


def backfill_failure_counts(session: Session, run: AnalysisRun) -> int:
    """Fill ``LegacyDNA.failure_count`` from this run's ``Failure`` rows (run from
    ``DETECTING_FAILURES``, after failures are persisted). Recorded, not scored."""
    counts = _failure_count_by_component(session, run.id)
    if not counts:
        return 0
    n = 0
    for dna in session.scalars(select(LegacyDNA).where(LegacyDNA.run_id == run.id)).all():
        fc = counts.get(dna.component_id, 0)
        if dna.failure_count != fc:
            dna.failure_count = fc
            n += 1
    session.flush()
    return n


def refine_scores_with_measured_coverage(
    session: Session,
    run: AnalysisRun,
    snapshot: RepositorySnapshot,
    coverage_xml_text: str,
) -> RefineSummary:
    fmap = parse_coverage_xml(coverage_xml_text)
    if not fmap:
        return RefineSummary(refined=0)

    comps = {
        c.id: c
        for c in session.scalars(
            select(Component).where(Component.snapshot_id == snapshot.id)
        ).all()
    }
    debt_by_component: dict[str, float] = {}
    for f in session.scalars(
        select(TechnicalDebtFinding).where(TechnicalDebtFinding.run_id == run.id)
    ).all():
        if f.component_id:
            debt_by_component[f.component_id] = (
                debt_by_component.get(f.component_id, 0.0)
                + SEVERITY_WEIGHT[f.severity.value]
            )

    risk_by_component = {
        r.component_id: r
        for r in session.scalars(
            select(RiskAssessment).where(RiskAssessment.run_id == run.id)
        ).all()
    }
    hotspot_by_component = {
        h.component_id: h
        for h in session.scalars(select(Hotspot).where(Hotspot.run_id == run.id)).all()
    }

    refined = 0
    for dna in session.scalars(select(LegacyDNA).where(LegacyDNA.run_id == run.id)).all():
        comp = comps.get(dna.component_id)
        if comp is None:
            continue
        real_cov = round(component_coverage_pct(comp, fmap), 4)
        fb = dna.factor_breakdown or {}
        defaulted = fb.get("defaulted_signals", {})
        sig = LegacyRiskSignals(
            complexity=dna.complexity, churn=dna.churn, coverage=real_cov,
            coupling=dna.coupling, coupling_is_proxy=bool(fb.get("coupling_is_proxy")),
            assumption_count=dna.assumption_count or 0, debt_score=dna.debt_score,
            age_days=dna.age_days, age_is_defaulted=bool(defaulted.get("age")),
        )
        res = legacy_risk_score(sig, coverage_is_proxy=False)
        dna.coverage = real_cov
        dna.coverage_is_proxy = False
        dna.legacy_risk_score = res.score
        dna.category = res.category
        dna.confidence = res.confidence
        dna.factor_breakdown = res.factor_breakdown
        dna.produced_by = LEGACY_RISK_VERSION

        risk = risk_by_component.get(dna.component_id)
        if risk is not None:
            risk.score = res.score
            risk.category = res.category
            risk.confidence = res.confidence
            risk.factor_breakdown = res.factor_breakdown

        hot = hotspot_by_component.get(dna.component_id)
        if hot is not None:
            debt_score = min(
                debt_by_component.get(dna.component_id, 0.0) / DEBT_SCORE_MAX, 1.0
            )
            h_res = hotspot_score(HotspotSignals(
                complexity=dna.complexity, churn=dna.churn, coverage=real_cov,
                coupling=dna.coupling, assumption_count=dna.assumption_count or 0,
                debt_score=debt_score,
            ))
            hot.score = h_res.score
            hot.classification = h_res.classification
            hot.reasons = h_res.reasons

        refined += 1

    session.flush()
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.EXECUTING, classification=Classification.FACT,
            summary=f"Refined {refined} component score(s) with measured coverage",
            produced_by=COVERAGE_REFINE_VERSION, confidence=1.0,
        )
    )
    session.flush()
    log.info(
        "coverage refine complete",
        extra={"extra_fields": {"run_id": run.id, "refined": refined}},
    )
    return RefineSummary(refined=refined)
