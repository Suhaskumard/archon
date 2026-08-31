"""Sandbox contract (spec sections 12, 36).

    run(spec) -> ExecutionResult

Every field on ``ExecutionSpec`` has a security-relevant default sourced from
``SandboxSettings``/``RepositoryLimits`` - callers only need to override ``command``
and ``workspace``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path

from archon.config import get_settings
from archon.workspace.manager import Workspace


@dataclass(frozen=True)
class ExecutionSpec:
    workspace: Workspace
    command: list[str]
    timeout_seconds: int = field(
        default_factory=lambda: get_settings().limits.max_sandbox_runtime_seconds
    )
    cpu_limit: float = field(default_factory=lambda: get_settings().sandbox.cpu_limit)
    memory_mb: int = field(default_factory=lambda: get_settings().sandbox.memory_mb)
    pids_limit: int = field(default_factory=lambda: get_settings().sandbox.pids_limit)
    allow_install: bool = False  # opt-in egress-filtered install phase - NOT implemented (raises)
    out_dir: str = "out"  # relative to /work; copied out after the run


@dataclass(frozen=True)
class ExecutionResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    out_files: dict[str, Path] = field(default_factory=dict)  # relative name -> local path


class Sandbox(abc.ABC):
    @abc.abstractmethod
    def run(self, spec: ExecutionSpec) -> ExecutionResult: ...
