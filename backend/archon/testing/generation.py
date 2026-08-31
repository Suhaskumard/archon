"""AI test generation, mock provider (spec sections 13-14, 33, 35).

Every scenario the mock ``TestGeneration`` AI proposes is rendered to a pytest test
function. All of one candidate's syntactically-valid scenarios are **static-validated**
(parses, no banned constructs) individually, then combined into a single file and
**sandbox-validated** together (actually collected and run in the Docker sandbox) in
ONE container per candidate - not one per scenario, which would multiply container
spin-up cost (each several seconds under Docker Desktop) by up to six per candidate and
made full pipeline runs impractically slow. A scenario that fails static validation is
still persisted (for visibility) with ``validated=False`` and ``validation_errors`` set
- never silently dropped. Only validated tests are written into the workspace, so an
invalid generated test can never pollute the combined suite the ``EXECUTING`` stage
runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archon.core.artifacts import write_text
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Dependency,
    Evidence,
    Execution,
    RepositorySnapshot,
    TestCase,
)
from archon.domain.ai_schemas import TestGeneration
from archon.domain.enums import (
    Classification,
    ComponentKind,
    DependencyKind,
    ExecutionKind,
    Stage,
    TestCaseKind,
    TestCaseOrigin,
)
from archon.providers.ai import AIOutputError, AIProviderError, get_ai_provider
from archon.sandbox import get_sandbox
from archon.sandbox.base import ExecutionSpec
from archon.testing._safety import parses, source_is_safe
from archon.testing.characterization import _find_function_node, _module_dotted_path, _param_names
from archon.testing.gaps import identify_untested_components
from archon.workspace.manager import Workspace

log = get_logger("archon.testing.generation")

TEST_GENERATION_VERSION = "test_generation.v1"
_MAX_TARGETS = 3


@dataclass
class TestGenerationSummary:
    generated: int
    validated: int

    def as_dict(self) -> dict:
        return {"generated": self.generated, "validated": self.validated}


def _render_scenario_body(func: str, suffix: str, input_args: dict, expected_behavior: str) -> str:
    call = f"{func}(**{input_args!r})"
    lines = [f"def test_ai_{func}_{suffix}():"]
    if expected_behavior.strip().lower().startswith("raise"):
        lines += ["    with pytest.raises(Exception):", f"        {call}"]
    else:
        lines.append(f"    {call}")
    return "\n".join(lines) + "\n"


def run_test_generation(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
) -> TestGenerationSummary:
    session.execute(
        delete(TestCase).where(TestCase.run_id == run.id, TestCase.origin == TestCaseOrigin.AI)
    )
    session.flush()

    candidates = [
        c for c in identify_untested_components(session, run, snapshot)
        if c.kind is ComponentKind.FUNCTION
    ][:_MAX_TARGETS]

    repo_dir = workspace.resolve_within("repo")
    (repo_dir / "tests").mkdir(parents=True, exist_ok=True)
    ai = get_ai_provider()
    sandbox = get_sandbox()
    generated = 0
    validated_count = 0

    for component in candidates:
        file_path = repo_dir / component.path
        try:
            source = file_path.read_text(encoding="utf-8")
        except OSError:
            continue
        node = _find_function_node(source, component.name, component.start_line or -1)
        if node is None:
            continue

        has_dependencies = session.scalar(
            select(Dependency.id).where(
                Dependency.snapshot_id == snapshot.id,
                Dependency.src_component_id == component.id,
                Dependency.kind == DependencyKind.CALLS.value,
                Dependency.dst_component_id.is_not(None),
            ).limit(1)
        ) is not None

        context = {
            "component": {
                "id": component.id, "qualified_name": component.qualified_name,
                "name": component.name, "params": _param_names(node),
            },
            "has_raise": "raise" in source,
            "has_dependencies": has_dependencies,
            "known_refs": {"component": {component.qualified_name}},
        }
        try:
            result = ai.complete_structured("test_generation", TestGeneration, context)
        except (AIProviderError, AIOutputError) as exc:
            session.add(
                Evidence(
                    run_id=run.id, stage=Stage.GENERATING_TESTS, classification=Classification.INFERENCE,
                    summary=f"AI test generation failed for {component.qualified_name}: {exc}",
                    produced_by=TEST_GENERATION_VERSION, confidence=1.0,
                )
            )
            continue

        module = _module_dotted_path(component.path)
        generated += len(result.scenarios)

        # static-validate each scenario individually, then combine only the safe ones
        # into ONE file so the sandbox run costs one container per candidate.
        statically_valid: list[tuple[int, object, str]] = []
        rejected: list[tuple[int, object, str]] = []
        for i, scenario in enumerate(result.scenarios):
            suffix = f"{i}_{scenario.kind.lower()}"
            body = _render_scenario_body(component.name, suffix, scenario.input_args, scenario.expected_behavior)
            full_src = f"from {module} import {component.name}\n\nimport pytest\n\n{body}"
            ok, err = parses(full_src)
            if not ok:
                rejected.append((i, scenario, f"static: {err}"))
            elif not source_is_safe(full_src):
                rejected.append((i, scenario, "static: contains a banned construct"))
            else:
                statically_valid.append((i, scenario, body))

        sandbox_ok = True
        exec_row_id = None
        if statically_valid:
            combined = f"from {module} import {component.name}\n\nimport pytest\n\n" + "\n".join(
                body for _, _, body in statically_valid
            )
            harness_name = f"_archon_gentest_{component.id}.py"
            (repo_dir / harness_name).write_text(combined, encoding="utf-8")
            started = datetime.now(UTC)
            sres = sandbox.run(ExecutionSpec(
                workspace=workspace, command=["python3", "-m", "pytest", "-q", "--tb=short", harness_name],
            ))
            ended = datetime.now(UTC)
            (repo_dir / harness_name).unlink(missing_ok=True)

            # a collection-level failure (bad import, etc.) invalidates the whole batch;
            # otherwise every statically-valid scenario counts as sandbox-validated
            # regardless of individual pass/fail - the bar is "actually runs", not "passes".
            sandbox_ok = "error" not in sres.stdout.lower() or sres.exit_code in (0, 1)

            stdout_art = write_text(session, run.id, f"gentest_stdout_{component.id}", sres.stdout, stage=Stage.GENERATING_TESTS)
            stderr_art = write_text(session, run.id, f"gentest_stderr_{component.id}", sres.stderr, stage=Stage.GENERATING_TESTS)
            exec_row = Execution(
                run_id=run.id, kind=ExecutionKind.GENERATED_TESTS, sandbox_ref=None,
                command=["python3", "-m", "pytest", "-q", harness_name], exit_code=sres.exit_code,
                passed=0, failed=0, errors=0 if sandbox_ok else len(statically_valid),
                timed_out=sres.timed_out, duration_ms=sres.duration_ms,
                stdout_ref=stdout_art.id, stderr_ref=stderr_art.id, coverage_ref=None,
                started_at=started, ended_at=ended, produced_by=TEST_GENERATION_VERSION,
            )
            session.add(exec_row)
            session.flush()
            exec_row_id = exec_row.id

            if sandbox_ok:
                rel_path = f"tests/archon_generated_{component.name}.py"
                (repo_dir / rel_path).write_text(combined, encoding="utf-8")

        for i, scenario, body in statically_valid:
            is_valid = sandbox_ok
            validation_errors = None if is_valid else ["sandbox: collection error in the combined batch"]
            if is_valid:
                validated_count += 1
            body_art = write_text(
                session, run.id, f"gentest_body_{component.id}_{i}", body,
                stage=Stage.GENERATING_TESTS, ext=".py", mime="text/x-python",
            )
            session.add(
                TestCase(
                    run_id=run.id, snapshot_id=snapshot.id, component_id=component.id,
                    kind=TestCaseKind(scenario.kind),
                    path=f"tests/archon_generated_{component.name}.py" if is_valid else "",
                    name=f"test_ai_{component.name}_{i}_{scenario.kind.lower()}",
                    body_ref=body_art.id, origin=TestCaseOrigin.AI,
                    validated=is_valid, validation_errors=validation_errors,
                    produced_by=TEST_GENERATION_VERSION,
                )
            )
            session.add(
                Evidence(
                    run_id=run.id, stage=Stage.GENERATING_TESTS,
                    classification=Classification.FACT if is_valid else Classification.INFERENCE,
                    summary=(
                        f"AI-generated {scenario.kind} test for {component.qualified_name} "
                        f"{'validated' if is_valid else 'rejected: sandbox collection error'}"
                    ),
                    produced_by=TEST_GENERATION_VERSION, confidence=1.0,
                    refs={"execution_id": exec_row_id} if exec_row_id else None,
                )
            )

        for i, scenario, reason in rejected:
            body_art = write_text(
                session, run.id, f"gentest_body_{component.id}_{i}",
                _render_scenario_body(component.name, f"{i}_{scenario.kind.lower()}", scenario.input_args, scenario.expected_behavior),
                stage=Stage.GENERATING_TESTS, ext=".py", mime="text/x-python",
            )
            session.add(
                TestCase(
                    run_id=run.id, snapshot_id=snapshot.id, component_id=component.id,
                    kind=TestCaseKind(scenario.kind), path="",
                    name=f"test_ai_{component.name}_{i}_{scenario.kind.lower()}",
                    body_ref=body_art.id, origin=TestCaseOrigin.AI,
                    validated=False, validation_errors=[reason],
                    produced_by=TEST_GENERATION_VERSION,
                )
            )
            session.add(
                Evidence(
                    run_id=run.id, stage=Stage.GENERATING_TESTS, classification=Classification.INFERENCE,
                    summary=f"AI-generated {scenario.kind} test for {component.qualified_name} rejected: {reason}",
                    produced_by=TEST_GENERATION_VERSION, confidence=1.0,
                )
            )
        session.flush()

    log.info(
        "test generation complete",
        extra={"extra_fields": {"run_id": run.id, "generated": generated, "validated": validated_count}},
    )
    return TestGenerationSummary(generated=generated, validated=validated_count)
