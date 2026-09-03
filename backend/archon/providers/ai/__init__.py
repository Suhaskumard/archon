"""AI provider abstraction (spec sections 13-14, 18).

Deterministic work stays deterministic; the AI layer only *interprets* evidence the
deterministic engines have already produced. A ``MockAIProvider`` (rule-based, offline,
reproducible) is the default and backs every test. A real ``ClaudeAIProvider`` slots in
behind the same interface without touching callers.
"""

from __future__ import annotations

from functools import lru_cache

from archon.config import get_settings
from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.providers.ai.base import (
    AICallRecord,
    AIOutputError,
    AIProvider,
    AIProviderError,
    drain_ai_calls,
)
from archon.providers.ai.mock import MockAIProvider

__all__ = [
    "AIProvider",
    "AIProviderError",
    "AIOutputError",
    "AICallRecord",
    "drain_ai_calls",
    "MockAIProvider",
    "get_ai_provider",
    "reset_ai_provider_cache",
]


@lru_cache
def get_ai_provider() -> AIProvider:
    name = get_settings().ai_provider.lower()
    if name == "mock":
        return MockAIProvider()
    if name == "claude":
        from archon.providers.ai.claude import ClaudeAIProvider

        return ClaudeAIProvider()
    raise ArchonError(
        ErrorCode.AI_PROVIDER_ERROR,
        f"unknown AI provider {name!r}",
        recoverability=Recoverability.NON_RECOVERABLE,
        suggested_action="Set ARCHON_AI_PROVIDER to 'mock'.",
    )


def reset_ai_provider_cache() -> None:
    get_ai_provider.cache_clear()
