"""Change Safety scoring engine (spec sections 31-32).

``change_safety.v1`` - unlike Legacy Risk/Hotspot ("higher = riskier"), Change Safety's
contract is "higher = **safer**". Each negative-direction signal (complexity, coupling,
centrality, caller risk, assumptions, churn) is inverted (``1 - normalized``) before
weighting, so the weighted sum is natively a safety sum - never a risk-sum-then-subtract.
This keeps ``explain()``'s per-factor contributions directly interpretable as "how much
this factor added to safety".

Coverage has no real data yet (Phase 8) and is always a documented proxy (see
``change_safety_run.py``); historical change-success rate and historical failures have
no data at all yet (Phase 9+) and are omitted from the signal set and the confidence
denominator entirely - never defaulted to a false "fully safe" or "fully risky" value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from archon.analysis.scoring.thresholds import (
    ASSUMPTION_COUNT_SCALE,
    CENTRALITY_SCALE,
    CHANGE_SAFETY_THRESHOLDS,
    CHANGE_SAFETY_WEIGHTS,
    CHURN_SCALE,
    COMPLEXITY_SCALE,
    COUPLING_SCALE,
)
from archon.domain.enums import ChangeSafetyCategory

CHANGE_SAFETY_VERSION = "change_safety.v1"


def _norm(value: float | None, scale: float) -> float:
    if value is None or scale <= 0:
        return 0.0
    return max(0.0, min(value / scale, 1.0))


@dataclass
class ChangeSafetySignals:
    coverage: float | None = None  # 0..1, higher = more covered (always a proxy this phase)
    complexity: float | None = None
    coupling: float | None = None  # fan_in + fan_out
    coupling_is_proxy: bool = False
    centrality: float | None = None  # betweenness_centrality, already 0..1
    caller_risk_ratio: float | None = None  # at-risk callers / total callers, 0..1
    caller_count: int = 0
    assumption_count: int = 0
    churn: float | None = None


@dataclass
class ScoreResult:
    score: float
    category: str
    confidence: float
    factor_breakdown: dict = field(default_factory=dict)

    def explain(self) -> dict:
        return dict(self.factor_breakdown)


def _category(score: float) -> str:
    t = CHANGE_SAFETY_THRESHOLDS
    if score >= t["CAUTION"]:
        return ChangeSafetyCategory.SAFE.value
    if score >= t["RISKY"]:
        return ChangeSafetyCategory.CAUTION.value
    if score >= t["DANGEROUS"]:
        return ChangeSafetyCategory.RISKY.value
    return ChangeSafetyCategory.DANGEROUS.value


def change_safety_score(signals: ChangeSafetySignals) -> ScoreResult:
    coverage = max(0.0, min(signals.coverage if signals.coverage is not None else 0.0, 1.0))
    caller_risk = max(
        0.0, min(signals.caller_risk_ratio if signals.caller_risk_ratio is not None else 0.0, 1.0)
    )
    # every entry here is already "higher = safer" (inverted where the raw signal is bad)
    safe_norm = {
        "coverage": coverage,
        "complexity": 1.0 - _norm(signals.complexity, COMPLEXITY_SCALE),
        "coupling": 1.0 - _norm(signals.coupling, COUPLING_SCALE),
        "centrality": 1.0 - _norm(signals.centrality, CENTRALITY_SCALE),
        "caller_risk_ratio": 1.0 - caller_risk,
        "assumption_count": 1.0 - _norm(signals.assumption_count, ASSUMPTION_COUNT_SCALE),
        "churn": 1.0 - _norm(signals.churn, CHURN_SCALE),
    }
    contributions = {k: round(safe_norm[k] * w, 6) for k, w in CHANGE_SAFETY_WEIGHTS.items()}
    total_weight = sum(CHANGE_SAFETY_WEIGHTS.values())
    score = round(100.0 * sum(contributions.values()) / total_weight, 2) if total_weight else 0.0

    # confidence = fraction of signals backed by real data. coverage is *always* a
    # documented proxy this phase; historical change-success-rate/failures are omitted
    # entirely (never silently treated as fully-safe or fully-risky).
    defaulted = {
        "coverage": True,
        "complexity": signals.complexity is None,
        "coupling": signals.coupling is None or signals.coupling_is_proxy,
        "centrality": signals.centrality is None,
        "caller_risk_ratio": False,
        "assumption_count": False,
        "churn": signals.churn is None,
    }
    real = sum(1 for d in defaulted.values() if not d)
    confidence = round(real / len(defaulted), 4) if defaulted else 0.0

    return ScoreResult(
        score=score,
        category=_category(score),
        confidence=confidence,
        factor_breakdown={
            "safe_normalized": safe_norm,
            "weighted": contributions,
            "weights": dict(CHANGE_SAFETY_WEIGHTS),
            "defaulted_signals": defaulted,
            "coverage_is_proxy": True,
            "coupling_is_proxy": signals.coupling_is_proxy,
            "caller_count": signals.caller_count,
            "historical_change_success_rate_omitted": True,
            "historical_failures_omitted": True,
        },
    )
