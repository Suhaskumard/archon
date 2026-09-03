"""In-process fixed-window rate limiter (Phase 20)."""

from __future__ import annotations

import pytest

from archon.core.errors import ArchonError, ErrorCode
from archon.core.ratelimit import RateLimiter


def test_allows_up_to_the_limit_then_blocks():
    rl = RateLimiter(limit=3, window_seconds=60)
    assert [rl.allow("ip-a") for _ in range(3)] == [True, True, True]
    assert rl.allow("ip-a") is False


def test_windows_are_per_key():
    rl = RateLimiter(limit=1, window_seconds=60)
    assert rl.allow("ip-a") is True
    assert rl.allow("ip-b") is True
    assert rl.allow("ip-a") is False


def test_window_expiry_lets_calls_through_again(monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr("archon.core.ratelimit.time.monotonic", lambda: t["now"])
    rl = RateLimiter(limit=1, window_seconds=10)
    assert rl.allow("ip") is True
    assert rl.allow("ip") is False
    t["now"] += 11
    assert rl.allow("ip") is True


def test_check_raises_structured_429():
    rl = RateLimiter(limit=1, window_seconds=60)
    rl.check("ip", resource="run creation")
    with pytest.raises(ArchonError) as e:
        rl.check("ip", resource="run creation")
    assert e.value.code is ErrorCode.RATE_LIMITED
    assert e.value.http_status == 429


def test_reset_clears_windows():
    rl = RateLimiter(limit=1, window_seconds=60)
    rl.allow("ip")
    rl.reset()
    assert rl.allow("ip") is True
