"""Identifier helpers.

ARCHON ids are k-sortable, URL-safe strings: ``<prefix>_<26-char lowercase base32>``.
The random part is a ULID-style value (48-bit timestamp + 80-bit randomness) so ids sort
by creation time without a central sequence.
"""

from __future__ import annotations

import os
import time

_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_CROCKFORD[rem])
    return "".join(reversed(chars))


def new_ulid() -> str:
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    return _encode(ts_ms, 10) + _encode(rand, 16)


def new_id(prefix: str) -> str:
    if not prefix or not prefix.isalnum():
        raise ValueError(f"invalid id prefix: {prefix!r}")
    return f"{prefix}_{new_ulid()}"
