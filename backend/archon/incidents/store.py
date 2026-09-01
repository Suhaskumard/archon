"""Incident memory (spec section 44) - the ``RECORDING_INCIDENT`` stage plus the
retrieval helper ``investigation/engine.py`` calls before every root-cause AI op.

An incident is scoped to the *repository*, not a run/snapshot - it must still match
after later commits, so its ``failure_signature`` deliberately excludes
snapshot-scoped identifiers (``component_id``, line numbers) and keys on the
exception type plus the innermost stack frame's file/function instead (spec:
"retrieval by failure-signature + stack + component overlap" - the exact-match
signature already encodes both the exception type and the stack's innermost frame,
which is sufficient for this phase's single recognized bug pattern).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Evidence,
    Failure,
    Incident,
    Investigation,
    Patch,
    PatchVerification,
    TestCase,
)
from archon.domain.enums import Classification, PatchState, Stage, TestCaseOrigin

log = get_logger("archon.incidents")

INCIDENT_MEMORY_VERSION = "incident_memory.v1"


def compute_failure_signature(failure: Failure) -> str:
    frames = failure.parsed_frames or []
    innermost = frames[-1] if frames else {}
    key = f"{failure.exception_type}|{innermost.get('path', '')}|{innermost.get('func', '')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def find_similar_incidents(session: Session, repo_id: str, signature: str) -> list[Incident]:
    return list(
        session.scalars(
            select(Incident)
            .where(Incident.repo_id == repo_id, Incident.failure_signature == signature)
            .order_by(Incident.created_at.desc())
        ).all()
    )


def _collect_evidence_ids(session: Session, run_id: str, investigation_id: str, patch_id: str | None) -> list[str]:
    rows = session.scalars(select(Evidence).where(Evidence.run_id == run_id)).all()
    ids = []
    for e in rows:
        refs = e.refs or {}
        if refs.get("investigation_id") == investigation_id or (
            patch_id and refs.get("patch_id") == patch_id
        ):
            ids.append(e.id)
    return ids


def _regression_test_ids(session: Session, run_id: str, failure: Failure, component_id: str | None) -> list[str]:
    ids = []
    matching = session.scalars(
        select(TestCase).where(TestCase.run_id == run_id, TestCase.name == failure.test_identifier)
    ).all()
    ids.extend(t.id for t in matching)
    if component_id:
        char_tests = session.scalars(
            select(TestCase).where(
                TestCase.run_id == run_id, TestCase.component_id == component_id,
                TestCase.origin == TestCaseOrigin.CHARACTERIZATION,
            )
        ).all()
        ids.extend(t.id for t in char_tests)
    return ids


@dataclass
class IncidentSummary:
    recorded: int

    def as_dict(self) -> dict:
        return {"recorded": self.recorded}


def record_incidents(session: Session, run: AnalysisRun) -> IncidentSummary:
    session.execute(delete(Incident).where(Incident.run_id == run.id))
    session.flush()

    verified_patches = session.scalars(
        select(Patch).where(Patch.run_id == run.id, Patch.state == PatchState.VERIFIED)
    ).all()

    recorded = 0
    for patch in verified_patches:
        investigation = session.get(Investigation, patch.investigation_id)
        if investigation is None:
            continue
        failure = session.get(Failure, investigation.failure_id)
        if failure is None:
            continue
        verification = session.scalar(
            select(PatchVerification).where(PatchVerification.patch_id == patch.id)
        )
        component_id = investigation.affected_component_ids[0] if investigation.affected_component_ids else None
        root_cause = (
            investigation.root_cause_hypotheses[0]["statement"]
            if investigation.root_cause_hypotheses else investigation.summary
        )

        incident = Incident(
            run_id=run.id, repo_id=run.repository_id,
            failure_signature=compute_failure_signature(failure),
            failure_summary=f"{failure.test_identifier}: {failure.exception_type}: {failure.message}",
            root_cause=root_cause,
            evidence_ids=_collect_evidence_ids(session, run.id, investigation.id, patch.id),
            affected_component_ids=investigation.affected_component_ids,
            fix_ref=patch.diff_ref, patch_id=patch.id,
            regression_test_ids=_regression_test_ids(session, run.id, failure, component_id),
            verification_id=verification.id if verification else None,
            confidence=investigation.confidence, produced_by=INCIDENT_MEMORY_VERSION,
        )
        session.add(incident)
        session.flush()
        recorded += 1

        session.add(
            Evidence(
                run_id=run.id, stage=Stage.RECORDING_INCIDENT, classification=Classification.FACT,
                summary=f"Recorded incident for {failure.test_identifier} (patch {patch.strategy!r} verified)",
                produced_by=INCIDENT_MEMORY_VERSION, confidence=1.0,
                refs={"incident_id": incident.id, "patch_id": patch.id},
            )
        )
        session.flush()

    if not verified_patches:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.RECORDING_INCIDENT, classification=Classification.FACT,
                summary="No verified patches this run - nothing to record",
                produced_by=INCIDENT_MEMORY_VERSION, confidence=1.0,
            )
        )
        session.flush()

    log.info("incidents recorded", extra={"extra_fields": {"run_id": run.id, "recorded": recorded}})
    return IncidentSummary(recorded=recorded)
