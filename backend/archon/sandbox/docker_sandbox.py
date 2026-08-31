"""``DockerSandbox`` - the Docker driver for the ``Sandbox`` ABC (spec sections 12, 36).

Shells out to the ``docker`` CLI with argument lists (never ``shell=True``), mirroring
``providers/repo/gitcli.py``'s safety conventions, rather than adding the ``docker``
Python SDK as a dependency.

Per execution: one ephemeral container, non-root user, read-only root fs with tmpfs
``/work`` + ``/tmp``, all capabilities dropped, no new privileges, no network by
default, CPU/memory/pids/ulimits capped, empty environment (no ARCHON/GitHub/Anthropic
secret is ever passed in), only the snapshot workspace copied in (never bind-mounted),
outputs copied out of ``/work/<out_dir>``, and the container is always removed.

``docker cp`` only works against a *running* container - tmpfs mounts aren't attached
until ``docker start`` - so the container's main process is a placeholder ``sleep``
that outlives the real command; the actual command runs via ``docker exec`` once the
workspace has been copied in, with stdout/stderr redirected to files inside ``/work``
(not captured from the ``docker exec`` client directly) so output survives even if the
exec client itself has to be killed on a wall-clock timeout.
"""

from __future__ import annotations

import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.logging import get_logger, redact
from archon.sandbox.base import ExecutionResult, ExecutionSpec, Sandbox

log = get_logger("archon.sandbox")

_UID_GID = "1000:1000"
_SLEEP_BUFFER_SECONDS = 30  # placeholder process outlives the real command by this much


def _docker(args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", *args]
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, shell=False, check=False,
        )
    except FileNotFoundError as exc:
        raise ArchonError(
            ErrorCode.SANDBOX_UNAVAILABLE,
            "docker executable not found on PATH",
            recoverability=Recoverability.TRANSIENT,
            suggested_action="Install Docker Desktop and ensure `docker` is on PATH.",
        ) from exc


def _is_daemon_unreachable(stderr: str) -> bool:
    s = stderr.lower()
    return "cannot connect to the docker daemon" in s or "error during connect" in s


class DockerSandbox(Sandbox):
    def __init__(self, image: str) -> None:
        self.image = image

    def run(self, spec: ExecutionSpec) -> ExecutionResult:
        if spec.allow_install:
            raise ArchonError(
                ErrorCode.VALIDATION,
                "opt-in egress-filtered dependency install is not implemented yet",
                recoverability=Recoverability.NON_RECOVERABLE,
                suggested_action="Run offline (allow_install=False) until this ships.",
            )

        container_id = self._create(spec)
        started = time.monotonic()
        try:
            self._start(container_id)
            self._copy_in(container_id, spec)
            exit_code, timed_out = self._exec(container_id, spec)
            out_files = self._copy_out(container_id, spec)
            stdout = self._read_text(out_files.pop("stdout.log", None))
            stderr = self._read_text(out_files.pop("stderr.log", None))
            duration_ms = int((time.monotonic() - started) * 1000)
            return ExecutionResult(
                exit_code=exit_code, stdout=stdout, stderr=stderr,
                duration_ms=duration_ms, timed_out=timed_out, out_files=out_files,
            )
        finally:
            _docker(["rm", "-f", container_id])

    # --- steps ----------------------------------------------------------------------

    def _create(self, spec: ExecutionSpec) -> str:
        mem = f"{spec.memory_mb}m"
        placeholder = ["sleep", str(spec.timeout_seconds + _SLEEP_BUFFER_SECONDS)]
        args = [
            "create",
            "--label", "archon.managed=true",
            "--label", f"archon.workspace_id={spec.workspace.id}",
            "--user", _UID_GID,
            "--read-only",
            "--tmpfs", "/work:rw,uid=1000,gid=1000,size=128m",
            "--tmpfs", "/tmp:rw,uid=1000,gid=1000,size=32m",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--network", "none",
            "--cpus", str(spec.cpu_limit),
            "--memory", mem,
            "--memory-swap", mem,
            "--pids-limit", str(spec.pids_limit),
            "--ulimit", "nofile=1024:1024",
            # NOT --ulimit nproc: RLIMIT_NPROC is a per-real-UID kernel limit shared
            # across every container using uid 1000 on this host (not per-container),
            # so it can starve unrelated containers instead of just this one.
            # --pids-limit above is the correct, per-container cgroup control.
            "--workdir", "/work",
            self.image,
            *placeholder,
        ]
        proc = _docker(args)
        if proc.returncode != 0:
            if _is_daemon_unreachable(proc.stderr):
                raise ArchonError(
                    ErrorCode.SANDBOX_UNAVAILABLE, "docker daemon is unreachable",
                    context={"stderr": redact(proc.stderr.strip())[:1000]},
                    recoverability=Recoverability.TRANSIENT,
                    suggested_action="Start Docker Desktop and retry.",
                )
            raise ArchonError(
                ErrorCode.CONTAINER_START_FAILED, "docker create failed",
                context={"stderr": redact(proc.stderr.strip())[:1000]},
                recoverability=Recoverability.TRANSIENT,
                suggested_action="Check the sandbox image exists (`make sandbox-image`) and retry.",
            )
        return proc.stdout.strip()

    def _start(self, container_id: str) -> None:
        proc = _docker(["start", container_id])
        if proc.returncode != 0:
            raise ArchonError(
                ErrorCode.CONTAINER_START_FAILED, "docker start failed",
                context={"stderr": redact(proc.stderr.strip())[:1000]},
                recoverability=Recoverability.TRANSIENT,
            )

    def _copy_in(self, container_id: str, spec: ExecutionSpec) -> None:
        # `docker cp` unconditionally refuses to write into any --read-only container,
        # even though /work is a genuinely-writable tmpfs mount (a blanket docker-cli
        # check, not mount-aware) - so pipe a tarball in via `docker exec` instead,
        # which writes through the real (writable) mount like any other process would.
        repo_dir = spec.workspace.resolve_within("repo")
        tar_proc = subprocess.run(
            ["tar", "-cf", "-", "-C", str(repo_dir), "."],
            capture_output=True, shell=False, check=False,
        )
        if tar_proc.returncode != 0:
            raise ArchonError(
                ErrorCode.CONTAINER_START_FAILED, "failed to archive workspace for the sandbox",
                context={"stderr": redact(tar_proc.stderr.decode(errors="replace").strip())[:1000]},
                recoverability=Recoverability.TRANSIENT,
            )
        proc = subprocess.run(
            ["docker", "exec", "-i", container_id, "sh", "-c", "mkdir -p /work && tar -xf - -C /work"],
            input=tar_proc.stdout, capture_output=True, shell=False, check=False,
        )
        if proc.returncode != 0:
            raise ArchonError(
                ErrorCode.CONTAINER_START_FAILED, "failed to copy workspace into sandbox",
                context={"stderr": redact(proc.stderr.decode(errors="replace").strip())[:1000]},
                recoverability=Recoverability.TRANSIENT,
            )

    def _exec(self, container_id: str, spec: ExecutionSpec) -> tuple[int | None, bool]:
        out = shlex.quote(spec.out_dir)
        cmd_str = " ".join(shlex.quote(c) for c in spec.command)
        # stdout/stderr are redirected to files inside /work so they survive even if
        # the `docker exec` client below has to be killed on a wall-clock timeout -
        # `docker logs` only captures the placeholder `sleep` process, not `exec`'d ones.
        script = f"mkdir -p {out} && {{ {cmd_str}; }} > {out}/stdout.log 2> {out}/stderr.log"
        args = ["exec", container_id, "sh", "-c", script]
        try:
            proc = _docker(args, timeout=spec.timeout_seconds)
        except subprocess.TimeoutExpired:
            _docker(["kill", container_id])
            return None, True
        return proc.returncode, False

    def _copy_out(self, container_id: str, spec: ExecutionSpec) -> dict[str, Path]:
        # `docker cp` can't see into tmpfs-mounted paths at all (it reads the storage
        # driver's layer diff, which tmpfs never joins) - so, like `_copy_in`, stream a
        # tarball out via `docker exec` instead of using `docker cp`.
        # A plain mkdtemp (not TemporaryDirectory) - it must outlive this method so the
        # caller can read the files; the caller (execution runner) removes it once done.
        local_out = Path(tempfile.mkdtemp(prefix="archon-sandbox-out-"))
        tar_proc = subprocess.run(
            ["docker", "exec", container_id, "tar", "-cf", "-", "-C", f"/work/{spec.out_dir}", "."],
            capture_output=True, shell=False, check=False,
        )
        if tar_proc.returncode != 0:
            # out dir may legitimately be empty/absent (e.g. killed before mkdir ran) -
            # never fail the whole execution over missing output artifacts.
            log.info(
                "no sandbox output files copied out",
                extra={"extra_fields": {
                    "container": container_id,
                    "stderr": tar_proc.stderr.decode(errors="replace").strip()[:500],
                }},
            )
            return {}
        extract = subprocess.run(
            ["tar", "-xf", "-", "-C", str(local_out)],
            input=tar_proc.stdout, capture_output=True, shell=False, check=False,
        )
        if extract.returncode != 0:
            log.warning(
                "failed to extract sandbox output archive",
                extra={"extra_fields": {"stderr": extract.stderr.decode(errors="replace")[:500]}},
            )
            return {}
        out_files: dict[str, Path] = {}
        for p in local_out.rglob("*"):
            if p.is_file():
                out_files[str(p.relative_to(local_out))] = p
        return out_files

    @staticmethod
    def _read_text(path: Path | None) -> str:
        if path is None:
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
