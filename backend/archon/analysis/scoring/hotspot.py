"""Hotspot scoring engine (spec section 29).

``hotspot.v1`` - the same normalized signal set as Legacy Risk, combined with a
multiplicative "signals overlap" bonus when 3+ signals are independently elevated (spec
sec 29's overlap idea): a component that is simultaneously high-churn, high-complexity
*and* highly coupled is worse than the sum of its parts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from archon.analysis.scoring.thresholds import (
    ASSUMPTION_COUNT_SCALE,
    CHURN_SCALE,
    COMPLEXITY_SCALE,
    COUPLING_SCALE,
    HOTSPOT_OVERLAP_BONUS,
    HOTSPOT_OVERLAP_MIN_SIGNALS,
    HOTSPOT_OVERLAP_SIGNAL_THRESHOLD,
    HOTSPOT_THRESHOLDS,
    HOTSPOT_WEIGHTS,
)
from archon.domain.enums import HotspotClassification

HOTSPOT_VERSION = "hotspot.v1"


def _norm(value: float | None, scale: float) -> float:
    if value is None or scale <= 0:
        return 0.0
    return max(0.0, min(value / scale, 1.0))


@dataclass
class HotspotSignals:
    complexity: float | None = None
    churn: float | None = None
    coverage: float | None = None
    coupling: float | None = None
    assumption_count: int = 0
    debt_score: float | None = None  # 0..1


@dataclass
class ScoreResult:
    score: float
    classification: str
    reasons: dict = field(default_factory=dict)

    def explain(self) -> dict:
        return dict(self.reasons)


def _classification(score: float) -> str:
    t = HOTSPOT_THRESHOLDS
    if score >= t["RISKY"]:
        return HotspotClassification.CRITICAL.value
    if score >= t["WATCH"]:
        return HotspotClassification.RISKY.value
    if score >= t["STABLE"]:
        return HotspotClassification.WATCH.value
    return HotspotClassification.STABLE.value


def hotspot_score(signals: HotspotSignals) -> ScoreResult:
    coverage = max(0.0, min(signals.coverage if signals.coverage is not None else 0.0, 1.0))
    normalized = {
        "complexity": _norm(signals.complexity, COMPLEXITY_SCALE),
        "churn": _norm(signals.churn, CHURN_SCALE),
        "coverage_gap": 1.0 - coverage,
        "coupling": _norm(signals.coupling, COUPLING_SCALE),
        "assumption_count": _norm(signals.assumption_count, ASSUMPTION_COUNT_SCALE),
        "debt_score": max(0.0, min(signals.debt_score or 0.0, 1.0)),
    }
    contributions = {k: round(normalized[k] * w, 6) for k, w in HOTSPOT_WEIGHTS.items()}
    total_weight = sum(HOTSPOT_WEIGHTS.values())
    base = 100.0 * sum(contributions.values()) / total_weight if total_weight else 0.0

    elevated = sorted(k for k, v in normalized.items() if v >= HOTSPOT_OVERLAP_SIGNAL_THRESHOLD)
    overlap = len(elevated) >= HOTSPOT_OVERLAP_MIN_SIGNALS
    score = round(min(base * HOTSPOT_OVERLAP_BONUS, 100.0), 2) if overlap else round(base, 2)

    return ScoreResult(
        score=score,
        classification=_classification(score),
        reasons={
            "normalized": normalized,
            "weighted": contributions,
            "weights": dict(HOTSPOT_WEIGHTS),
            "elevated_signals": elevated,
            "overlap_bonus_applied": overlap,
        },
    )
