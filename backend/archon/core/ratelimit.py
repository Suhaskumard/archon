"""In-process per-client fixed-window rate limiting (spec section 16, abuse controls).

Single-process only: each API / worker process keeps its own window map. A multi-replica
deployment behind a shared limiter (Redis, an ingress) is the documented next step - this
covers the single-node case the compose stack runs and every test.
"""

from __future__ import annotations

import threading
import time

from archon.core.errors import ArchonError, ErrorCode, Recoverability


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            hits = [t for t in self._hits.get(key, ()) if t > cutoff]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            # opportunistic GC so idle keys don't leak
            if len(self._hits) > 4096:
                self._hits = {
                    k: [t for t in v if t > cutoff]
                    for k, v in self._hits.items()
                    if any(t > cutoff for t in v)
                }
            return True

    def check(self, key: str, *, resource: str) -> None:
        if not self.allow(key):
            raise ArchonError(
                ErrorCode.RATE_LIMITED,
                f"rate limit exceeded for {resource}",
                context={"limit": self.limit, "window_seconds": self.window},
                recoverability=Recoverability.RECOVERABLE,
                suggested_action=f"Retry after ~{int(self.window)}s.",
            )

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
