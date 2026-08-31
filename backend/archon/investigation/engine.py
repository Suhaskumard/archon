"""Root-cause investigation (spec section 38) - the ``INVESTIGATING`` stage.

Assembles context around a ``Failure`` (the implicated ``Component``, its detected
``Assumption`` rows, git metrics) and calls the AI ``root_cause_analysis`` operation.
Proceeds to healing only past a documented confidence threshold (§38) - a failure the
mock provider can't explain gets ``confidence=UNKNOWN`` and is honestly skipped, not
silently guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Assumption,
    Component,
    Evidence,
    Failure,
    Investigation,
    RepositorySnapshot,
)
from archon.domain.ai_schemas import ROOT_CAUSE_SCHEMA_VERSION, RootCauseAnalysis
from archon.domain.enums import Classification, Confidence, Stage
from archon.providers.ai import get_ai_provider

log = get_logger("archon.investigation")

INVESTIGATION_VERSION = "investigation.v1"
# Only a MEDIUM+ confidence root cause proceeds to patch generation (spec section 38).
PATCH_GENERATION_CONFIDENCE_THRESHOLD = Confidence.MEDIUM.score


def _implicated_component(session: Session, failure: Failure) -> Component | None:
    for frame in reversed(failure.parsed_frames or []):
        cid = frame.get("component_id")
        if cid:
            comp = session.get(Component, cid)
            if comp:
                return comp
    return None


@dataclass
class InvestigationSummary:
    investigated: int
    gated_in: int

    def as_dict(self) -> dict:
        return {"investigated": self.investigated, "gated_in": self.gated_in}


def investigate_failures(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
) -> InvestigationSummary:
    session.execute(delete(Investigation).where(Investigation.run_id == run.id))
    session.flush()

    failures = session.scalars(select(Failure).where(Failure.run_id == run.id)).all()
    ai = get_ai_provider()
    investigated = 0
    gated_in = 0

    for failure in failures:
        component = _implicated_component(session, failure)
        assumptions = (
            session.scalars(select(Assumption).where(Assumption.component_id == component.id)).all()
            if component else []
        )

        context = {
            "failure": {
                "test_identifier": failure.test_identifier,
                "exception_type": failure.exception_type,
                "message": failure.message,
            },
            "component": (
                {
                    "id": component.id, "qualified_name": component.qualified_name,
                    "path": component.path, "name": component.name,
                } if component else None
            ),
            "assumptions": [
                {"kind": a.kind, "description": a.description, "location": a.location} for a in assumptions
            ],
            "known_refs": {"component": {component.qualified_name}} if component else {},
        }
        result = ai.complete_structured("root_cause_analysis", RootCauseAnalysis, context)

        hypotheses = [
            {
                "statement": h.statement, "confidence": h.confidence.value,
                "evidence": [e.model_dump() for e in h.evidence],
            }
            for h in result.hypotheses
        ]
        top_confidence = result.hypotheses[0].confidence.score if result.hypotheses else 0.0

        investigation = Investigation(
            run_id=run.id, failure_id=failure.id, summary=result.summary,
            root_cause_hypotheses=hypotheses,
            affected_component_ids=[component.id] if component else [],
            recommended_verification=result.recommended_verification,
            confidence=top_confidence, ai_schema_version=ROOT_CAUSE_SCHEMA_VERSION,
            produced_by=INVESTIGATION_VERSION,
        )
        session.add(investigation)
        session.flush()
        investigated += 1

        gated = top_confidence >= PATCH_GENERATION_CONFIDENCE_THRESHOLD
        if gated:
            gated_in += 1
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.INVESTIGATING,
                classification=result.classification, confidence=top_confidence,
                summary=f"Investigated {failure.test_identifier}: {result.summary}"[:512],
                detail=(
                    "Proceeding to patch generation." if gated
                    else f"Confidence below {PATCH_GENERATION_CONFIDENCE_THRESHOLD} threshold - skipping healing."
                ),
                produced_by=INVESTIGATION_VERSION,
                refs={"investigation_id": investigation.id, "gated_in": gated},
            )
        )
        session.flush()

    if not failures:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.INVESTIGATING, classification=Classification.FACT,
                summary="No failures to investigate", produced_by=INVESTIGATION_VERSION, confidence=1.0,
            )
        )
        session.flush()

    log.info(
        "failures investigated",
        extra={"extra_fields": {"run_id": run.id, "investigated": investigated, "gated_in": gated_in}},
    )
    return InvestigationSummary(investigated=investigated, gated_in=gated_in)
