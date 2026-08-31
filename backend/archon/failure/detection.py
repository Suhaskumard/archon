"""Failure detection (spec section 37) - the ``DETECTING_FAILURES`` stage.

Parses the ``execution_junit`` artifact ``execution/runner.py`` already writes (never
read until now) for failing/erroring `<testcase>` elements, extracts a best-effort
stack trace from pytest's ``--tb=short`` text (``path:line: in func`` per frame),
resolves each frame to a ``Component`` when possible, and re-runs each failing test
once more through the sandbox to check reproducibility. Capped at 3 distinct failures
per run (the same container-count discipline Phase 8 learned the hard way).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archon.core.artifacts import read_text, write_text
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisArtifact,
    AnalysisRun,
    Component,
    Evidence,
    Execution,
    Failure,
    RepositorySnapshot,
)
from archon.domain.enums import Classification, ComponentKind, Stage
from archon.sandbox import get_sandbox
from archon.sandbox.base import ExecutionSpec
from archon.workspace.manager import Workspace

log = get_logger("archon.failure")

FAILURE_DETECTION_VERSION = "failure_detection.v1"
_MAX_FAILURES = 3
_FRAME_RE = re.compile(r"^(?P<path>\S+\.py):(?P<line>\d+): in (?P<func>\S+)$", re.MULTILINE)
_EXC_RE = re.compile(r"^E\s+(?P<exc>[\w.]+)(?::\s*(?P<msg>.*))?$", re.MULTILINE)


def _parse_junit_failures(xml_text: str) -> list[dict]:
    """Returns one dict per failing/erroring ``<testcase>``: identifier, message,
    exception type, and the raw text (for frame extraction)."""
    if not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    out = []
    for tc in root.iter("testcase"):
        el = tc.find("failure")
        if el is None:
            el = tc.find("error")
        if el is None:
            continue
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        text = (el.text or "") + (el.get("message") or "")
        exc_matches = list(_EXC_RE.finditer(text))
        if exc_matches:
            exc_type = exc_matches[-1].group("exc")
            msg = (exc_matches[-1].group("msg") or "").strip()
        else:
            exc_type = el.get("type") or "AssertionError"
            msg = el.get("message") or ""
        out.append({
            "test_identifier": f"{classname}.{name}" if classname else name,
            "message": msg or (el.get("message") or ""),
            "exception_type": exc_type,
            "text": text,
        })
    return out


def _parse_frames(text: str) -> list[dict]:
    return [
        {"path": m.group("path"), "line": int(m.group("line")), "func": m.group("func")}
        for m in _FRAME_RE.finditer(text)
    ]


def _resolve_component(session: Session, snapshot: RepositorySnapshot, frame: dict) -> str | None:
    comp = session.scalar(
        select(Component).where(
            Component.snapshot_id == snapshot.id,
            Component.path == frame["path"],
            Component.kind.in_((ComponentKind.FUNCTION, ComponentKind.METHOD)),
            Component.start_line.is_not(None),
            Component.end_line.is_not(None),
            Component.start_line <= frame["line"],
            Component.end_line >= frame["line"],
        )
    )
    return comp.id if comp else None


def _node_id(test_identifier: str) -> str:
    """``pkg.mod.test_name`` (junit classname.name) -> ``pkg/mod.py::test_name``."""
    module_part, _, test_name = test_identifier.rpartition(".")
    return f"{module_part.replace('.', '/')}.py::{test_name}"


@dataclass
class FailureDetectionSummary:
    detected: int
    reproducible: int

    def as_dict(self) -> dict:
        return {"detected": self.detected, "reproducible": self.reproducible}


def detect_failures(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot,
    execution: Execution, workspace: Workspace,
) -> FailureDetectionSummary:
    session.execute(delete(Failure).where(Failure.run_id == run.id))
    session.flush()

    art = session.scalar(
        select(AnalysisArtifact).where(
            AnalysisArtifact.run_id == run.id, AnalysisArtifact.kind == "execution_junit"
        )
    )
    parsed = _parse_junit_failures(read_text(art)) if art else []
    parsed = parsed[:_MAX_FAILURES]

    sandbox = get_sandbox()
    detected = 0
    reproducible = 0

    for entry in parsed:
        frames = _parse_frames(entry["text"])
        # innermost repo frame last in a traceback; skip frames pytest emits for its
        # own assertion-rewriting machinery by requiring the path to look like a
        # relative repo path (already true for pytest's --tb=short frame format).
        resolved_frames = []
        for f in frames:
            f = {**f, "component_id": _resolve_component(session, snapshot, f)}
            resolved_frames.append(f)

        node_id = _node_id(entry["test_identifier"])
        result = sandbox.run(ExecutionSpec(
            workspace=workspace, command=["python3", "-m", "pytest", "-q", "--tb=short", node_id],
        ))
        is_reproducible = result.exit_code != 0

        stack_art = None
        if entry["text"]:
            stack_art = write_text(
                session, run.id, f"failure_stack_{entry['test_identifier']}", entry["text"],
                stage=Stage.DETECTING_FAILURES,
            )

        failure = Failure(
            run_id=run.id, execution_id=execution.id, test_identifier=entry["test_identifier"],
            message=entry["message"], exception_type=entry["exception_type"],
            stack_trace_ref=stack_art.id if stack_art else None, parsed_frames=resolved_frames,
            reproducible=is_reproducible, occurrences=2 if is_reproducible else 1,
            first_seen=datetime.now(UTC), produced_by=FAILURE_DETECTION_VERSION,
        )
        session.add(failure)
        session.flush()
        detected += 1
        if is_reproducible:
            reproducible += 1

        session.add(
            Evidence(
                run_id=run.id, stage=Stage.DETECTING_FAILURES, classification=Classification.FACT,
                summary=f"Detected failure in {entry['test_identifier']}: {entry['exception_type']}",
                detail=entry["message"], produced_by=FAILURE_DETECTION_VERSION, confidence=1.0,
                refs={"failure_id": failure.id, "reproducible": is_reproducible},
            )
        )
        session.flush()

    if not parsed:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.DETECTING_FAILURES, classification=Classification.FACT,
                summary="No test failures detected", produced_by=FAILURE_DETECTION_VERSION, confidence=1.0,
            )
        )
        session.flush()

    log.info(
        "failures detected",
        extra={"extra_fields": {"run_id": run.id, "detected": detected, "reproducible": reproducible}},
    )
    return FailureDetectionSummary(detected=detected, reproducible=reproducible)
