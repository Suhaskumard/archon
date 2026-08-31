from pathlib import Path

import pytest

from archon.sandbox.base import ExecutionResult, ExecutionSpec
from archon.workspace.manager import Workspace


def _ws() -> Workspace:
    return Workspace(id="ws_test", path=Path("/tmp/ws_test"))


def test_execution_spec_defaults_come_from_settings():
    spec = ExecutionSpec(workspace=_ws(), command=["echo", "hi"])
    assert spec.timeout_seconds > 0
    assert spec.cpu_limit > 0
    assert spec.memory_mb > 0
    assert spec.pids_limit > 0
    assert spec.allow_install is False
    assert spec.out_dir == "out"


def test_execution_spec_overrides_stick():
    spec = ExecutionSpec(
        workspace=_ws(), command=["sleep", "1"], timeout_seconds=5, pids_limit=8,
    )
    assert spec.timeout_seconds == 5
    assert spec.pids_limit == 8


def test_execution_spec_is_frozen():
    spec = ExecutionSpec(workspace=_ws(), command=["echo"])
    with pytest.raises(AttributeError):
        spec.command = ["rm"]  # type: ignore[misc]


def test_execution_result_defaults():
    result = ExecutionResult(exit_code=0, stdout="ok", stderr="", duration_ms=10, timed_out=False)
    assert result.out_files == {}
