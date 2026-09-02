"""Hotspot scoring stage runner (spec section 29).

Runs last in the Phase 5 stage order, so it reuses ``LegacyDNA`` rows (complexity, churn,
coupling, coverage-proxy, assumption_count - already computed by ``BUILDING_LEGACY_DNA``)
and the *full* 13-detector ``TechnicalDebtFinding`` set (only available after
``ANALYZING_TECH_DEBT`` has run) rather than recomputing anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.analysis.scoring._reuse import prior_run_over_snapshot
from archon.analysis.scoring.hotspot import HOTSPOT_VERSION, HotspotSignals, hotspot_score
from archon.analysis.scoring.thresholds import DEBT_SCORE_MAX, SEVERITY_WEIGHT
from archon.core.artifacts import write_json
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Evidence,
    Hotspot,
    LegacyDNA,
    RepositorySnapshot,
    TechnicalDebtFinding,
)
from archon.domain.enums import Classification, Stage

log = get_logger("archon.analysis.scoring.hotspots")

_ARTIFACT_KIND = "hotspots"
_MAX_CRITICAL_EVIDENCE = 15


@dataclass
class HotspotSummary:
    reused: bool
    scored: int
    by_classification: dict[str, int]
    artifact_ref: str | None = None

    def as_dict(self) -> dict:
        return {
            "reused": self.reused, "scored": self.scored,
            "by_classification": self.by_classification, "artifact": self.artifact_ref,
        }



def _write_artifact(session: Session, run: AnalysisRun, snapshot: RepositorySnapshot):
    rows = session.scalars(select(Hotspot).where(Hotspot.run_id == run.id)).all()
    return write_json(
        session, run.id, _ARTIFACT_KIND,
        {
            "schema": "archon.hotspots.v1",
            "snapshot_id": snapshot.id,
            "hotspots": [
                {
                    "component_id": r.component_id, "score": r.score,
                    "classification": r.classification, "reasons": r.reasons,
                }
                for r in rows
            ],
        },
        stage=Stage.SCORING_HOTSPOTS,
    )


def _clone_from_prior(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, prior_run_id: str
) -> HotspotSummary:
    rows = session.scalars(
        select(Hotspot).where(Hotspot.snapshot_id == snapshot.id, Hotspot.run_id == prior_run_id)
    ).all()
    by_classification: dict[str, int] = {}
    for r in rows:
        by_classification[r.classification] = by_classification.get(r.classification, 0) + 1
        session.add(
            Hotspot(
                run_id=run.id, snapshot_id=snapshot.id, component_id=r.component_id,
                score=r.score, classification=r.classification, reasons=r.reasons,
                evidence_ids=r.evidence_ids, engine_version=r.engine_version,
            )
        )
    session.flush()
    art = _write_artifact(session, run, snapshot)
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.SCORING_HOTSPOTS, classification=Classification.FACT,
            summary=f"Reused cached hotspot scoring for snapshot {snapshot.id} ({len(rows)} component(s))",
            produced_by=HOTSPOT_VERSION,
        )
    )
    session.flush()
    return HotspotSummary(
        reused=True, scored=len(rows), by_classification=by_classification, artifact_ref=art.ref,
    )


def run_hotspot_scoring(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
) -> HotspotSummary:
    prior = prior_run_over_snapshot(session, run, snapshot.id, Hotspot)
    if prior:
        return _clone_from_prior(session, run, snapshot, prior)

    dna_rows = session.scalars(select(LegacyDNA).where(LegacyDNA.run_id == run.id)).all()

    debt_by_component: dict[str, float] = {}
    for f in session.scalars(
        select(TechnicalDebtFinding).where(TechnicalDebtFinding.run_id == run.id)
    ).all():
        if not f.component_id:
            continue
        debt_by_component[f.component_id] = (
            debt_by_component.get(f.component_id, 0.0) + SEVERITY_WEIGHT[f.severity.value]
        )

    by_classification: dict[str, int] = {}
    for dna in dna_rows:
        debt_score = min(debt_by_component.get(dna.component_id, 0.0) / DEBT_SCORE_MAX, 1.0)
        signals = HotspotSignals(
            complexity=dna.complexity, churn=dna.churn, coverage=dna.coverage,
            coupling=dna.coupling, assumption_count=dna.assumption_count, debt_score=debt_score,
        )
        result = hotspot_score(signals)
        by_classification[result.classification] = by_classification.get(result.classification, 0) + 1
        session.add(
            Hotspot(
                run_id=run.id, snapshot_id=snapshot.id, component_id=dna.component_id,
                score=result.score, classification=result.classification, reasons=result.reasons,
                evidence_ids=None, engine_version=HOTSPOT_VERSION,
            )
        )
    session.flush()

    art = _write_artifact(session, run, snapshot)
    _emit_evidence(session, run, len(dna_rows), by_classification)
    log.info(
        "hotspots scored",
        extra={"extra_fields": {"run_id": run.id, "scored": len(dna_rows), "by_classification": by_classification}},
    )
    return HotspotSummary(
        reused=False, scored=len(dna_rows), by_classification=by_classification, artifact_ref=art.ref,
    )


def _emit_evidence(
    session: Session, run: AnalysisRun, scored: int, by_classification: dict[str, int]
) -> None:
    cls_str = ", ".join(f"{k}={v}" for k, v in sorted(by_classification.items()))
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.SCORING_HOTSPOTS, classification=Classification.INFERENCE,
            summary=f"Hotspot-scored {scored} component(s): {cls_str}",
            produced_by=HOTSPOT_VERSION, confidence=1.0, refs={"by_classification": by_classification},
        )
    )
    critical = session.scalars(
        select(Hotspot).where(Hotspot.run_id == run.id, Hotspot.classification == "CRITICAL")
    ).all()
    for row in critical[:_MAX_CRITICAL_EVIDENCE]:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.SCORING_HOTSPOTS, classification=Classification.HYPOTHESIS,
                summary=f"Critical hotspot (score={row.score}) for component {row.component_id}",
                detail=", ".join(row.reasons.get("elevated_signals", [])),
                produced_by=HOTSPOT_VERSION, confidence=0.7,
            )
        )
    session.flush()
