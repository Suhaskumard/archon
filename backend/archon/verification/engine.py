"""Patch verification + rollback (spec sections 41-42) - the ``VERIFYING_PATCH`` /
``REGRESSION_VERIFYING`` stages.

Every ranked candidate (bounded - at most two per investigation, from
``healing/generation.py``) is tried in its own throwaway workspace copy (the original
checkout other stages use is never touched - Principle 11). ``VERIFIED`` only when the
originally-failing test now passes, the full existing+characterization+generated suite
has no new failures, and the snippet swap applied cleanly (spec section 41, verbatim
AND). On rejection, the clone is simply discarded (``WorkspaceManager.cleanup``) - the
original was never mutated, so "restore" is exactly "nothing to restore" - and the
next-ranked candidate is tried regardless (spec section 42) rather than stopping at the
first VERIFIED one: trying every (cheap, capped) candidate surfaces every verdict for
the human-approval step (spec section 43) instead of hiding a rejected candidate that
happened to rank just below the winner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.core.artifacts import write_text
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Component,
    Evidence,
    Execution,
    Failure,
    Investigation,
    Patch,
    PatchVerification,
    RepositorySnapshot,
)
from archon.domain.enums import (
    Classification,
    ExecutionKind,
    PatchState,
    Stage,
    VerificationVerdict,
)
from archon.execution.runner import _PYTEST_COMMAND, _parse_pytest_summary
from archon.failure.detection import _node_id, _parse_junit_failures
from archon.healing.ranking import rank_verified
from archon.sandbox import get_sandbox
from archon.sandbox.base import ExecutionSpec
from archon.workspace.manager import Workspace, WorkspaceManager

log = get_logger("archon.verification")

PATCH_VERIFICATION_VERSION = "patch_verification.v1"


def _run_and_record(
    session: Session, run: AnalysisRun, clone: Workspace, command: list[str],
    kind: ExecutionKind, label: str,
) -> tuple[Execution, str]:
    sandbox = get_sandbox()
    started = datetime.now(UTC)
    result = sandbox.run(ExecutionSpec(workspace=clone, command=command))
    ended = datetime.now(UTC)
    passed, failed, errors = _parse_pytest_summary(result.stdout)
    junit_text = ""
    if "junit.xml" in result.out_files:
        junit_text = result.out_files["junit.xml"].read_text(encoding="utf-8", errors="replace")
    stdout_art = write_text(session, run.id, f"verify_stdout_{label}", result.stdout, stage=Stage.VERIFYING_PATCH)
    stderr_art = write_text(session, run.id, f"verify_stderr_{label}", result.stderr, stage=Stage.VERIFYING_PATCH)
    execution = Execution(
        run_id=run.id, kind=kind, sandbox_ref=None, command=command, exit_code=result.exit_code,
        passed=passed, failed=failed, errors=errors, timed_out=result.timed_out,
        duration_ms=result.duration_ms, stdout_ref=stdout_art.id, stderr_ref=stderr_art.id,
        coverage_ref=None, started_at=started, ended_at=ended, produced_by=PATCH_VERIFICATION_VERSION,
    )
    session.add(execution)
    session.flush()
    return execution, junit_text


@dataclass
class VerificationSummary:
    tried: int
    verified: bool

    def as_dict(self) -> dict:
        return {"tried": self.tried, "verified": self.verified}


def verify_patches(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
) -> VerificationSummary:
    pre_patch_failing = {
        f.test_identifier for f in session.scalars(select(Failure).where(Failure.run_id == run.id)).all()
    }
    patches = session.scalars(
        select(Patch)
        .where(Patch.run_id == run.id, Patch.state == PatchState.TESTING)
        .order_by(Patch.rank_score.desc())
    ).all()

    wm = WorkspaceManager()
    tried = 0
    found_verified = False

    for patch in patches:
        investigation = session.get(Investigation, patch.investigation_id)
        failure = session.get(Failure, investigation.failure_id) if investigation else None
        component = session.get(Component, patch.target_component_ids[0]) if patch.target_component_ids else None

        clone = wm.clone(workspace, label="verify")
        tried += 1
        try:
            execution_ids: list[str] = []
            original_failure_fixed = regression_pass = existing_tests_pass = characterization_pass = False
            new_critical_failures = 0
            applies_cleanly = False

            if component is not None:
                file_path = clone.resolve_within("repo") / component.path
                original = file_path.read_text(encoding="utf-8")
                occurrences = original.count(patch.old_snippet)
                applies_cleanly = occurrences == 1
                if applies_cleanly:
                    file_path.write_text(
                        original.replace(patch.old_snippet, patch.new_snippet, 1), encoding="utf-8"
                    )

            if applies_cleanly and failure is not None:
                node_id = _node_id(failure.test_identifier)
                exec_a, _ = _run_and_record(
                    session, run, clone, ["python3", "-m", "pytest", "-q", "--tb=short", node_id],
                    ExecutionKind.PATCH_VERIFICATION, f"{patch.id}_original",
                )
                execution_ids.append(exec_a.id)
                original_failure_fixed = exec_a.exit_code == 0

                exec_b, junit_b = _run_and_record(
                    session, run, clone, list(_PYTEST_COMMAND), ExecutionKind.REGRESSION, f"{patch.id}_full",
                )
                execution_ids.append(exec_b.id)
                post_failing = {f["test_identifier"] for f in _parse_junit_failures(junit_b)}
                new_critical_failures = len(post_failing - (pre_patch_failing - {failure.test_identifier}))
                regression_pass = new_critical_failures == 0
                existing_tests_pass = exec_b.failed == 0 and exec_b.errors == 0

                exec_c, _ = _run_and_record(
                    session, run, clone,
                    ["python3", "-m", "pytest", "-q", "--tb=short", "tests", "-k", "characterize"],
                    ExecutionKind.CHARACTERIZATION, f"{patch.id}_characterization",
                )
                execution_ids.append(exec_c.id)
                # exit code 5 = pytest "no tests collected" (no characterization tests
                # exist this run) - vacuously fine, not a failure.
                characterization_pass = exec_c.exit_code in (0, 5)

            verdict = (
                VerificationVerdict.VERIFIED
                if applies_cleanly and original_failure_fixed and regression_pass
                and existing_tests_pass and characterization_pass
                else VerificationVerdict.REJECTED
            )

            pv = PatchVerification(
                run_id=run.id, patch_id=patch.id, original_failure_fixed=original_failure_fixed,
                characterization_pass=characterization_pass, regression_pass=regression_pass,
                existing_tests_pass=existing_tests_pass, new_critical_failures=new_critical_failures,
                applies_cleanly=applies_cleanly, verdict=verdict, execution_ids=execution_ids,
                evidence_ids=None, produced_by=PATCH_VERIFICATION_VERSION,
            )
            session.add(pv)
            session.flush()

            rr = rank_verified(
                static_validation_clean=not patch.static_validation.get("errors"),
                lines_changed=patch.lines_added + patch.lines_removed, verification=pv,
            )
            patch.rank_score = rr.score
            patch.rank_breakdown = rr.explain()
            patch.state = PatchState.VERIFIED if verdict is VerificationVerdict.VERIFIED else PatchState.REJECTED
            session.flush()

            session.add(
                Evidence(
                    run_id=run.id, stage=Stage.VERIFYING_PATCH,
                    classification=Classification.FACT if verdict is VerificationVerdict.VERIFIED else Classification.INFERENCE,
                    summary=f"Patch {patch.strategy!r} verdict: {verdict.value}",
                    detail=(
                        f"original_failure_fixed={original_failure_fixed} regression_pass={regression_pass} "
                        f"existing_tests_pass={existing_tests_pass} characterization_pass={characterization_pass} "
                        f"applies_cleanly={applies_cleanly}"
                    ),
                    produced_by=PATCH_VERIFICATION_VERSION, confidence=1.0,
                    refs={"patch_id": patch.id, "verification_id": pv.id},
                )
            )
            session.flush()

            if verdict is VerificationVerdict.VERIFIED:
                found_verified = True
        finally:
            wm.cleanup(clone)

    if not patches:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.VERIFYING_PATCH, classification=Classification.FACT,
                summary="No patches to verify", produced_by=PATCH_VERIFICATION_VERSION, confidence=1.0,
            )
        )
        session.flush()

    log.info(
        "patches verified",
        extra={"extra_fields": {"run_id": run.id, "tried": tried, "verified": found_verified}},
    )
    return VerificationSummary(tried=tried, verified=found_verified)
