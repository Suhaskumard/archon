"""Characterization workflow (spec section 33, Principle 14): target -> safety
analysis -> bounded safe input generation -> execute current behaviour in the sandbox
-> capture output -> emit a characterization test -> store a reproducible baseline.

Observed behaviour is explicitly **not** assumed correct - a characterization test pins
today's behaviour (including bugs) so a future change is caught, it is not a claim that
the behaviour is right. Scoped to module-level ``FUNCTION`` components only this phase
(``METHOD`` targets need instance construction, which this deterministic engine cannot
safely infer - declared out of scope, not silently skipped: see the evidence emitted
for each skip).
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from archon.core.artifacts import write_json, write_text
from archon.core.ids import new_id
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Characterization,
    Component,
    Evidence,
    Execution,
    RepositorySnapshot,
    TestCase,
)
from archon.domain.enums import (
    Classification,
    ComponentKind,
    ExecutionKind,
    Stage,
    TestCaseKind,
    TestCaseOrigin,
)
from archon.sandbox import get_sandbox
from archon.sandbox.base import ExecutionSpec
from archon.testing._safety import source_is_safe
from archon.testing.gaps import identify_untested_components
from archon.workspace.manager import Workspace

log = get_logger("archon.testing.characterization")

CHARACTERIZATION_VERSION = "characterization.v1"
_MAX_TARGETS = 3
_BOUNDED_VALUES = (0, 1, -1, "")


@dataclass
class CharacterizationSummary:
    characterized: int
    skipped: int

    def as_dict(self) -> dict:
        return {"characterized": self.characterized, "skipped": self.skipped}


def _module_dotted_path(path: str) -> str:
    return path.removesuffix(".py").replace("/", ".").replace("\\", ".")


def _find_function_node(source: str, name: str, start_line: int) -> ast.FunctionDef | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name and node.lineno == start_line:
            return node
    return None


def assess_target_safety(component: Component, source: str, node: ast.FunctionDef | None) -> tuple[bool, str]:
    if node is None:
        return False, "could not locate the function definition in source"
    if node.decorator_list:
        return False, "decorated functions are out of scope (calling semantics may differ)"
    if node.args.vararg or node.args.kwarg or node.args.kwonlyargs:
        return False, "*args/**kwargs/keyword-only signatures are out of scope"
    snippet = ast.get_source_segment(source, node) or ""
    if not source_is_safe(snippet):
        return False, "source contains a side-effecting/dangerous construct"
    return True, ""


def _param_names(node: ast.FunctionDef) -> list[str]:
    return [a.arg for a in node.args.args]


def generate_bounded_inputs(node: ast.FunctionDef) -> list[dict]:
    """Deterministic per-value input sets - the same uniform value assigned to every
    parameter (no type inference; a bad value simply produces an honestly-recorded
    exception, which is the whole point of characterization)."""
    params = _param_names(node)
    if not params:
        return [{}]
    return [dict.fromkeys(params, v) for v in _BOUNDED_VALUES]


def _exception_class_name(name: str) -> str:
    return name if hasattr(builtins, name) else "Exception"


def _render_characterization_test(module: str, func: str, observed: list[dict]) -> str:
    lines = [f"from {module} import {func}", "", "import pytest", ""]
    for i, obs in enumerate(observed):
        call = f"{func}(**{obs['input']!r})"
        lines.append(f"def test_characterize_{func}_{i}():")
        if obs["raised"]:
            exc = _exception_class_name(obs["raised"]["type"])
            lines.append(f"    with pytest.raises({exc}):")
            lines.append(f"        {call}")
        else:
            lines.append(f"    assert repr({call}) == {obs['returned']!r}")
        lines.append("")
    return "\n".join(lines)


def run_characterization(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
) -> CharacterizationSummary:
    session.execute(delete(Characterization).where(Characterization.run_id == run.id))
    session.execute(
        delete(TestCase).where(TestCase.run_id == run.id, TestCase.origin == TestCaseOrigin.CHARACTERIZATION)
    )
    session.flush()

    candidates = [
        c for c in identify_untested_components(session, run, snapshot)
        if c.kind is ComponentKind.FUNCTION
    ][:_MAX_TARGETS]

    repo_dir = workspace.resolve_within("repo")
    sandbox = get_sandbox()
    characterized = 0
    skipped = 0

    for component in candidates:
        file_path = repo_dir / component.path
        try:
            source = file_path.read_text(encoding="utf-8")
        except OSError:
            skipped += 1
            continue

        node = _find_function_node(source, component.name, component.start_line or -1)
        safe, reason = assess_target_safety(component, source, node)
        if not safe:
            skipped += 1
            session.add(
                Evidence(
                    run_id=run.id, stage=Stage.CHARACTERIZING, classification=Classification.INFERENCE,
                    summary=f"Skipped characterization of {component.qualified_name}: {reason}",
                    produced_by=CHARACTERIZATION_VERSION, confidence=1.0,
                )
            )
            continue

        inputs = generate_bounded_inputs(node)
        module = _module_dotted_path(component.path)
        harness_name = f"_archon_characterize_{new_id('h')}.py"
        harness_src = _CHARACTERIZE_HARNESS.format(
            module=module, func=component.name, inputs=json.dumps(inputs),
        )
        (repo_dir / harness_name).write_text(harness_src, encoding="utf-8")

        started = datetime.now(UTC)
        result = sandbox.run(ExecutionSpec(workspace=workspace, command=["python3", harness_name]))
        ended = datetime.now(UTC)

        observed: list[dict] = []
        if "characterize_result.json" in result.out_files:
            try:
                observed = json.loads(
                    result.out_files["characterize_result.json"].read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                observed = []

        if not observed:
            skipped += 1
            session.add(
                Evidence(
                    run_id=run.id, stage=Stage.CHARACTERIZING, classification=Classification.INFERENCE,
                    summary=f"Characterization run produced no output for {component.qualified_name}",
                    detail=(result.stderr or "")[:2000],
                    produced_by=CHARACTERIZATION_VERSION, confidence=1.0,
                )
            )
            continue

        baseline_hash = hashlib.sha256(
            json.dumps({"input_spec": inputs, "observed": observed}, sort_keys=True).encode("utf-8")
        ).hexdigest()

        output_art = write_json(
            session, run.id, f"characterization_output_{component.id}", observed,
            stage=Stage.CHARACTERIZING,
        )
        test_src = _render_characterization_test(module, component.name, observed)
        test_rel_path = f"tests/archon_characterization_{component.name}.py"
        (repo_dir / "tests").mkdir(parents=True, exist_ok=True)
        (repo_dir / test_rel_path).write_text(test_src, encoding="utf-8")
        body_art = write_text(
            session, run.id, f"characterization_test_{component.id}", test_src,
            stage=Stage.CHARACTERIZING, ext=".py", mime="text/x-python",
        )

        test_case = TestCase(
            run_id=run.id, snapshot_id=snapshot.id, component_id=component.id,
            kind=TestCaseKind.CHARACTERIZATION, path=test_rel_path,
            name=f"test_characterize_{component.name}", body_ref=body_art.id,
            origin=TestCaseOrigin.CHARACTERIZATION, validated=True,
            produced_by=CHARACTERIZATION_VERSION,
        )
        session.add(test_case)
        session.flush()

        session.add(
            Characterization(
                run_id=run.id, snapshot_id=snapshot.id, component_id=component.id,
                input_spec=inputs, observed_output_ref=output_art.id,
                observed_side_effects=[{
                    "stdout_len": len(result.stdout), "stderr_len": len(result.stderr),
                    "timed_out": result.timed_out,
                }],
                baseline_hash=baseline_hash, test_case_id=test_case.id,
                produced_by=CHARACTERIZATION_VERSION,
            )
        )

        stdout_art = write_text(
            session, run.id, f"characterization_stdout_{component.id}", result.stdout,
            stage=Stage.CHARACTERIZING,
        )
        stderr_art = write_text(
            session, run.id, f"characterization_stderr_{component.id}", result.stderr,
            stage=Stage.CHARACTERIZING,
        )
        session.add(
            Execution(
                run_id=run.id, kind=ExecutionKind.CHARACTERIZATION, sandbox_ref=None,
                command=["python3", harness_name], exit_code=result.exit_code,
                passed=0, failed=0, errors=0, timed_out=result.timed_out,
                duration_ms=result.duration_ms, stdout_ref=stdout_art.id, stderr_ref=stderr_art.id,
                coverage_ref=None, started_at=started, ended_at=ended,
                produced_by=CHARACTERIZATION_VERSION,
            )
        )
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.CHARACTERIZING, classification=Classification.FACT,
                summary=f"Captured a characterization baseline for {component.qualified_name}",
                detail=f"baseline_hash={baseline_hash[:16]} inputs={len(inputs)}",
                produced_by=CHARACTERIZATION_VERSION, confidence=1.0,
            )
        )
        characterized += 1
        session.flush()

    log.info(
        "characterization complete",
        extra={"extra_fields": {"run_id": run.id, "characterized": characterized, "skipped": skipped}},
    )
    return CharacterizationSummary(characterized=characterized, skipped=skipped)


_CHARACTERIZE_HARNESS = '''\
import importlib, json, sys, pathlib

MODULE = {module!r}
FUNC = {func!r}
INPUTS = {inputs}

results = []
for inp in INPUTS:
    for modname in list(sys.modules):
        if modname == MODULE or modname.startswith(MODULE + "."):
            del sys.modules[modname]
    try:
        mod = importlib.import_module(MODULE)
        fn = getattr(mod, FUNC)
        ret = fn(**inp)
        results.append({{"input": inp, "returned": repr(ret), "raised": None}})
    except Exception as e:
        results.append({{"input": inp, "returned": None, "raised": {{"type": type(e).__name__, "message": str(e)}}}})

pathlib.Path("out").mkdir(exist_ok=True)
pathlib.Path("out/characterize_result.json").write_text(json.dumps(results))
'''
