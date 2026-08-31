"""Existing-test execution engine (spec sections 12, 33, 36, 39, 41) - the
``EXECUTING`` stage.

Runs ``pytest`` over the workspace through the sandbox and persists one ``Execution``
row plus stdout/stderr/coverage/junit artifacts. Only ``ExecutionKind.EXISTING_TESTS``
is produced this phase; the rest of the vocabulary (characterization, generated tests,
patch verification, regression) is Phase 8-9's job, reusing this same engine.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from archon.core.artifacts import write_text
from archon.core.logging import get_logger
from archon.db.models import AnalysisRun, Evidence, Execution, RepositorySnapshot
from archon.domain.enums import Classification, ExecutionKind, Stage
from archon.sandbox import get_sandbox
from archon.sandbox.base import ExecutionSpec
from archon.workspace.manager import Workspace

log = get_logger("archon.execution")

EXECUTION_VERSION = "execution.v1"

_PYTEST_COMMAND = [
    "python3", "-m", "pytest", "-q", "--tb=short",
    "--junit-xml=out/junit.xml", "--cov=.", "--cov-branch", "--cov-report=xml:out/coverage.xml",
]
_COUNT_RE = re.compile(r"(\d+) (passed|failed|error(?:s)?)")


@dataclass
class ExecutionSummary:
    exit_code: int | None
    passed: int
    failed: int
    errors: int
    timed_out: bool
    duration_ms: int
    execution_id: str

    def as_dict(self) -> dict:
        return {
            "exit_code": self.exit_code, "passed": self.passed, "failed": self.failed,
            "errors": self.errors, "timed_out": self.timed_out,
            "duration_ms": self.duration_ms, "execution_id": self.execution_id,
        }


def _parse_pytest_summary(stdout: str) -> tuple[int, int, int]:
    passed = failed = errors = 0
    for count, word in _COUNT_RE.findall(stdout):
        n = int(count)
        if word == "passed":
            passed = n
        elif word == "failed":
            failed = n
        elif word.startswith("error"):
            errors = n
    return passed, failed, errors


def run_existing_tests(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
) -> ExecutionSummary:
    spec = ExecutionSpec(workspace=workspace, command=_PYTEST_COMMAND)
    sandbox = get_sandbox()
    started = datetime.now(UTC)
    result = sandbox.run(spec)
    ended = datetime.now(UTC)

    passed, failed, errors = _parse_pytest_summary(result.stdout)

    stdout_art = write_text(session, run.id, "execution_stdout", result.stdout, stage=Stage.EXECUTING)
    stderr_art = write_text(session, run.id, "execution_stderr", result.stderr, stage=Stage.EXECUTING)

    coverage_ref = None
    if "coverage.xml" in result.out_files:
        text = result.out_files["coverage.xml"].read_text(encoding="utf-8", errors="replace")
        cov_art = write_text(
            session, run.id, "execution_coverage", text,
            stage=Stage.EXECUTING, ext=".xml", mime="application/xml",
        )
        coverage_ref = cov_art.id
    if "junit.xml" in result.out_files:
        text = result.out_files["junit.xml"].read_text(encoding="utf-8", errors="replace")
        write_text(
            session, run.id, "execution_junit", text,
            stage=Stage.EXECUTING, ext=".xml", mime="application/xml",
        )

    # DockerSandbox copies output files into a plain mkdtemp (not auto-cleaned) so the
    # content above survives long enough to read - now that it's been read, remove it.
    if result.out_files:
        shutil.rmtree(next(iter(result.out_files.values())).parent, ignore_errors=True)

    execution = Execution(
        run_id=run.id, kind=ExecutionKind.EXISTING_TESTS, sandbox_ref=None,
        command=_PYTEST_COMMAND, exit_code=result.exit_code,
        passed=passed, failed=failed, errors=errors, timed_out=result.timed_out,
        duration_ms=result.duration_ms, stdout_ref=stdout_art.id, stderr_ref=stderr_art.id,
        coverage_ref=coverage_ref, started_at=started, ended_at=ended,
        produced_by=EXECUTION_VERSION,
    )
    session.add(execution)
    session.flush()

    session.add(
        Evidence(
            run_id=run.id, stage=Stage.EXECUTING, classification=Classification.FACT,
            summary=(
                f"Ran existing tests in the sandbox: {passed} passed, {failed} failed, "
                f"{errors} error(s) (exit_code={result.exit_code})"
            ),
            produced_by=EXECUTION_VERSION, confidence=1.0,
        )
    )
    session.flush()
    log.info(
        "existing tests executed",
        extra={"extra_fields": {
            "run_id": run.id, "execution_id": execution.id, "exit_code": execution.exit_code,
            "passed": passed, "failed": failed, "errors": errors,
        }},
    )
    return ExecutionSummary(
        exit_code=result.exit_code, passed=passed, failed=failed, errors=errors,
        timed_out=result.timed_out, duration_ms=result.duration_ms, execution_id=execution.id,
    )
