"""Legacy Risk scoring engine (spec section 27).

``legacy_risk.v1`` - a weighted sum of normalized [0, 1] signals, weighted so churn +
complexity + low coverage dominate (spec sec 7: a high-churn/high-complexity/low-coverage
component must rank riskier than a stable equivalent). ``confidence`` is the fraction of
signals backed by real data rather than a documented default/proxy - coverage-gap is
always a proxy in this phase (no real coverage data until Phase 8) and therefore always
counts against confidence; historical failures have no data at all yet (Phase 9) and are
omitted from the signal set entirely rather than defaulted to a false "zero risk".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from archon.analysis.scoring.thresholds import (
    AGE_SCALE_DAYS,
    ASSUMPTION_COUNT_SCALE,
    CHURN_SCALE,
    COMPLEXITY_SCALE,
    COUPLING_SCALE,
    LEGACY_RISK_THRESHOLDS,
    LEGACY_RISK_WEIGHTS,
)
from archon.domain.enums import RiskCategory

LEGACY_RISK_VERSION = "legacy_risk.v1"


def _norm(value: float | None, scale: float) -> float:
    if value is None or scale <= 0:
        return 0.0
    return max(0.0, min(value / scale, 1.0))


@dataclass
class LegacyRiskSignals:
    complexity: float | None = None
    churn: float | None = None
    coverage: float | None = None  # 0..1, higher = more covered (always a proxy this phase)
    coupling: float | None = None  # fan_in + fan_out
    coupling_is_proxy: bool = False  # true when borrowed from the owning module
    assumption_count: int = 0
    debt_score: float | None = None  # already normalized to 0..1
    age_days: int | None = None
    age_is_defaulted: bool = False
    failure_count: int | None = None  # never scored - kept only for the record (spec: no data yet)


@dataclass
class ScoreResult:
    score: float
    category: str
    confidence: float
    factor_breakdown: dict = field(default_factory=dict)

    def explain(self) -> dict:
        return dict(self.factor_breakdown)


def _category(score: float) -> str:
    t = LEGACY_RISK_THRESHOLDS
    if score >= t["HIGH"]:
        return RiskCategory.CRITICAL.value
    if score >= t["MODERATE"]:
        return RiskCategory.HIGH.value
    if score >= t["LOW"]:
        return RiskCategory.MODERATE.value
    return RiskCategory.LOW.value


def legacy_risk_score(signals: LegacyRiskSignals) -> ScoreResult:
    coverage = max(0.0, min(signals.coverage if signals.coverage is not None else 0.0, 1.0))
    normalized = {
        "complexity": _norm(signals.complexity, COMPLEXITY_SCALE),
        "churn": _norm(signals.churn, CHURN_SCALE),
        "coverage_gap": 1.0 - coverage,
        "coupling": _norm(signals.coupling, COUPLING_SCALE),
        "assumption_count": _norm(signals.assumption_count, ASSUMPTION_COUNT_SCALE),
        "debt_score": max(0.0, min(signals.debt_score or 0.0, 1.0)),
        "age": _norm(signals.age_days, AGE_SCALE_DAYS),
    }
    contributions = {k: round(normalized[k] * w, 6) for k, w in LEGACY_RISK_WEIGHTS.items()}
    total_weight = sum(LEGACY_RISK_WEIGHTS.values())
    score = round(100.0 * sum(contributions.values()) / total_weight, 2) if total_weight else 0.0

    # confidence = fraction of signals backed by real data. coverage-gap is *always* a
    # documented proxy this phase; historical failures are omitted from the count entirely
    # (never silently treated as a real zero-risk signal).
    defaulted = {
        "complexity": signals.complexity is None,
        "churn": signals.churn is None,
        "coverage_gap": True,
        "coupling": signals.coupling is None or signals.coupling_is_proxy,
        "assumption_count": False,
        "debt_score": signals.debt_score is None,
        "age": signals.age_days is None or signals.age_is_defaulted,
    }
    real = sum(1 for d in defaulted.values() if not d)
    confidence = round(real / len(defaulted), 4) if defaulted else 0.0

    return ScoreResult(
        score=score,
        category=_category(score),
        confidence=confidence,
        factor_breakdown={
            "normalized": normalized,
            "weighted": contributions,
            "weights": dict(LEGACY_RISK_WEIGHTS),
            "defaulted_signals": defaulted,
            "coverage_is_proxy": True,
            "coupling_is_proxy": signals.coupling_is_proxy,
            "historical_failures_omitted": True,
        },
    )
