"""Shared safety checks for Phase 8 (spec sections 33, 35).

The sandbox already contains real damage (network isolation, read-only rootfs,
non-root, no secrets in env) - these checks exist so characterization/generation
don't even *attempt* nonsensical or side-effecting targets, and so a skip is always
evidence-backed rather than silent.
"""

from __future__ import annotations

import ast

_BANNED_SUBSTRINGS = (
    "subprocess", "socket", "os.system", "os.remove", "os.unlink", "shutil.rmtree",
    "open(", "requests", "urllib", "__import__", "eval(", "exec(",
)


def source_is_safe(source: str) -> bool:
    """Reject source containing an obvious side-effecting / dangerous construct."""
    return not any(bad in source for bad in _BANNED_SUBSTRINGS)


def parses(source: str) -> tuple[bool, str | None]:
    """Static (syntax) validation: does ``source`` parse as Python at all."""
    try:
        ast.parse(source)
    except SyntaxError as exc:
        return False, str(exc)
    return True, None
