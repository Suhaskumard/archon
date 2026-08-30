"""Thin, safe wrapper around the git CLI (spec sections 18, 52).

* commands are always argument lists - ``shell=False``, no string interpolation;
* stderr/stdout are redacted before they enter an exception or a log;
* a non-zero exit becomes a typed ``ArchonError``.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.logging import get_logger, redact

log = get_logger("archon.git")

_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def looks_like_sha(ref: str) -> bool:
    return bool(_SHA_RE.match(ref))


def run_git(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    timeout: float = 300.0,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git", *args]
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",       # never block on credential prompts
        "GIT_ASKPASS": "echo",
        "GCM_INTERACTIVE": "never",
    }
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            shell=False,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - git missing
        raise ArchonError(
            ErrorCode.INTERNAL,
            "git executable not found on PATH",
            recoverability=Recoverability.NON_RECOVERABLE,
            suggested_action="Install git and ensure it is on PATH.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ArchonError(
            ErrorCode.TIMEOUT,
            "git command timed out",
            context={"args": redact(args), "timeout_s": timeout},
            recoverability=Recoverability.TRANSIENT,
            suggested_action="Retry, or reduce clone depth / history limits.",
        ) from exc

    if check and proc.returncode != 0:
        raise ArchonError(
            ErrorCode.CLONE_FAILED,
            "git command failed",
            context={
                "args": redact(args),
                "returncode": proc.returncode,
                "stderr": redact(proc.stderr.strip())[:2000],
            },
            recoverability=Recoverability.TRANSIENT,
            suggested_action="Check the repository URL, ref and network access.",
        )
    return proc


def dir_stats(path: Path) -> tuple[int, int]:
    """Return (size_bytes, file_count) for a checkout, ignoring the .git directory."""
    size = 0
    files = 0
    for root, dirs, names in os.walk(path):
        if ".git" in dirs:
            dirs.remove(".git")
        for n in names:
            fp = Path(root) / n
            try:
                size += fp.stat().st_size
                files += 1
            except OSError:  # pragma: no cover
                pass
    return size, files
