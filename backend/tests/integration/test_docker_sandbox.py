"""DockerSandbox integration tests (spec sections 12, 36) - real Docker required.

Skipped automatically if the daemon or the ``archon-sandbox:latest`` image is missing
(see ``sandbox_image_available`` in conftest.py).
"""

from __future__ import annotations

import time

from archon.sandbox.base import ExecutionSpec
from archon.sandbox.docker_sandbox import DockerSandbox


def _sandbox() -> DockerSandbox:
    return DockerSandbox("archon-sandbox:latest")


def test_echo_captures_stdout_and_exit_code(sandbox_workspace):
    result = _sandbox().run(
        ExecutionSpec(workspace=sandbox_workspace, command=["sh", "-c", "echo hello; exit 0"])
    )
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.timed_out is False


def test_nonzero_exit_code_captured(sandbox_workspace):
    result = _sandbox().run(
        ExecutionSpec(workspace=sandbox_workspace, command=["sh", "-c", "exit 7"])
    )
    assert result.exit_code == 7


def test_workspace_files_are_copied_in(sandbox_workspace):
    (sandbox_workspace.resolve_within("repo") / "hello.txt").write_text("hi from host\n")
    result = _sandbox().run(
        ExecutionSpec(workspace=sandbox_workspace, command=["cat", "hello.txt"])
    )
    assert result.stdout == "hi from host\n"


def test_timeout_kills_container_and_reports_timed_out(sandbox_workspace):
    t0 = time.monotonic()
    result = _sandbox().run(
        ExecutionSpec(workspace=sandbox_workspace, command=["sleep", "30"], timeout_seconds=2)
    )
    elapsed = time.monotonic() - t0
    assert result.timed_out is True
    assert result.exit_code is None
    assert elapsed < 15, "wall-clock kill did not fire promptly"


def test_runs_as_non_root_user(sandbox_workspace):
    result = _sandbox().run(ExecutionSpec(workspace=sandbox_workspace, command=["id", "-u"]))
    assert result.stdout.strip() == "1000"


def test_root_filesystem_is_read_only(sandbox_workspace):
    result = _sandbox().run(
        ExecutionSpec(workspace=sandbox_workspace, command=["sh", "-c", "echo x > /etc/pwned"])
    )
    assert result.exit_code != 0


def test_work_directory_is_writable(sandbox_workspace):
    result = _sandbox().run(
        ExecutionSpec(workspace=sandbox_workspace, command=["sh", "-c", "echo x > scratch.txt && cat scratch.txt"])
    )
    assert result.exit_code == 0
    assert result.stdout == "x\n"


def test_network_is_isolated_by_default(sandbox_workspace):
    script = "import socket; socket.create_connection(('8.8.8.8', 53), timeout=2)"
    t0 = time.monotonic()
    result = _sandbox().run(
        ExecutionSpec(workspace=sandbox_workspace, command=["python3", "-c", script], timeout_seconds=10)
    )
    elapsed = time.monotonic() - t0
    assert result.exit_code != 0
    assert result.timed_out is False
    assert elapsed < 5, "network call should fail immediately (unreachable), not wait out a timeout"
    assert "Network is unreachable" in result.stderr


def test_pids_limit_contains_fork_bomb(sandbox_workspace):
    script = (
        "import os, time\n"
        "n = 0\n"
        "try:\n"
        "    while n < 10000:\n"
        "        pid = os.fork()\n"
        "        if pid == 0:\n"
        "            time.sleep(5)\n"
        "            os._exit(0)\n"
        "        n += 1\n"
        "except OSError:\n"
        "    pass\n"
        "print('forked', n)\n"
    )
    t0 = time.monotonic()
    result = _sandbox().run(
        ExecutionSpec(
            workspace=sandbox_workspace, command=["python3", "-c", script],
            timeout_seconds=15, pids_limit=32,
        )
    )
    elapsed = time.monotonic() - t0
    assert result.timed_out is False
    assert elapsed < 10, "pids-limit should contain the fork bomb well before the timeout"
    forked = int(result.stdout.strip().split()[-1])
    assert forked <= 32 + 4, f"expected containment near pids_limit, forked {forked}"


def test_empty_environment_no_host_secret_leaks(sandbox_workspace, monkeypatch):
    monkeypatch.setenv("ARCHON_GITHUB_TOKEN", "ghp_fake_secret_for_test_only")
    result = _sandbox().run(
        ExecutionSpec(workspace=sandbox_workspace, command=["sh", "-c", "env"])
    )
    assert "ARCHON_GITHUB_TOKEN" not in result.stdout
    assert "ghp_fake_secret_for_test_only" not in result.stdout
    assert "ghp_fake_secret_for_test_only" not in result.stderr


def test_output_files_are_copied_out(sandbox_workspace):
    result = _sandbox().run(
        ExecutionSpec(
            workspace=sandbox_workspace,
            command=["sh", "-c", "mkdir -p out && echo report > out/report.txt"],
        )
    )
    assert "report.txt" in result.out_files
    assert result.out_files["report.txt"].read_text() == "report\n"


def test_container_is_removed_after_run(sandbox_workspace):
    import subprocess

    _sandbox().run(ExecutionSpec(workspace=sandbox_workspace, command=["true"]))
    proc = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"label=archon.workspace_id={sandbox_workspace.id}",
         "--format", "{{.ID}}"],
        capture_output=True, text=True,
    )
    assert proc.stdout.strip() == ""
