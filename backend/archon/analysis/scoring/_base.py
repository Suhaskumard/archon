"""Shared primitives for the versioned scoring engines (spec sections 27-31).

``legacy_risk`` and ``change_safety`` share the exact ``ScoreResult`` shape; ``hotspot``
uses its own (``classification`` / ``reasons``). All three share ``_norm`` and the
weighted-sum reduction.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def norm(value: float | None, scale: float) -> float:
    """Clamp ``value / scale`` to ``[0, 1]``; ``None`` / non-positive scale -> 0.0."""
    if value is None or scale <= 0:
        return 0.0
    return max(0.0, min(value / scale, 1.0))


def weighted_score(
    normalized: dict[str, float], weights: dict[str, float]
) -> tuple[float, dict[str, float]]:
    """Return ``(raw_score_0_to_100, per_key_contributions)`` for a weighted mean of
    already-normalized ``[0, 1]`` signals. The caller rounds the final score (engines
    that post-process it - e.g. Hotspot's overlap bonus - round only once, at the end)."""
    contributions = {k: round(normalized[k] * w, 6) for k, w in weights.items()}
    total = sum(weights.values())
    score = 100.0 * sum(contributions.values()) / total if total else 0.0
    return score, contributions


@dataclass
class ScoreResult:
    """The ``legacy_risk`` / ``change_safety`` output shape."""

    score: float
    category: str
    confidence: float
    factor_breakdown: dict = field(default_factory=dict)

    def explain(self) -> dict:
        return dict(self.factor_breakdown)
