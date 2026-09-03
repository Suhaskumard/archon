"""Shared API dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from fastapi import Request
from sqlalchemy.orm import Session

from archon.config import get_settings
from archon.core.ratelimit import RateLimiter
from archon.db.base import get_sessionmaker


def get_session() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@lru_cache
def _runs_limiter() -> RateLimiter:
    return RateLimiter(get_settings().rate_limit_runs_per_minute, 60.0)


@lru_cache
def _webhook_limiter() -> RateLimiter:
    return RateLimiter(get_settings().rate_limit_webhook_per_minute, 60.0)


def reset_rate_limiters() -> None:
    """Test hook - drop cached limiters and their windows."""
    _runs_limiter.cache_clear()
    _webhook_limiter.cache_clear()


def rate_limit_runs(request: Request) -> None:
    if get_settings().rate_limit_enabled:
        _runs_limiter().check(client_ip(request), resource="run creation")


def rate_limit_webhook(request: Request) -> None:
    if get_settings().rate_limit_enabled:
        _webhook_limiter().check(client_ip(request), resource="the webhook")
