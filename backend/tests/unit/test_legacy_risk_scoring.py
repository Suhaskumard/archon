from archon.analysis.scoring.legacy_risk import LegacyRiskSignals, legacy_risk_score


def _stable() -> LegacyRiskSignals:
    return LegacyRiskSignals(
        complexity=2, churn=1, coverage=0.5, coupling=1, coupling_is_proxy=False,
        assumption_count=0, debt_score=0.0, age_days=30, age_is_defaulted=False,
    )


def _risky() -> LegacyRiskSignals:
    return LegacyRiskSignals(
        complexity=20, churn=80, coverage=0.0, coupling=25, coupling_is_proxy=False,
        assumption_count=5, debt_score=1.0, age_days=800, age_is_defaulted=False,
    )


def test_risky_ranks_above_stable():
    stable = legacy_risk_score(_stable())
    risky = legacy_risk_score(_risky())
    assert risky.score > stable.score
    assert stable.category in ("LOW", "MODERATE")
    assert risky.category in ("HIGH", "CRITICAL")


def test_explain_breakdown_sums_to_score():
    result = legacy_risk_score(_risky())
    weighted = result.factor_breakdown["weighted"]
    total_weight = sum(result.factor_breakdown["weights"].values())
    recomputed = round(100.0 * sum(weighted.values()) / total_weight, 2)
    assert recomputed == result.score


def test_confidence_drops_with_more_defaulted_signals():
    real_data = legacy_risk_score(
        LegacyRiskSignals(complexity=5, churn=5, coverage=0.5, coupling=5, debt_score=0.2, age_days=100)
    )
    sparse = legacy_risk_score(LegacyRiskSignals())  # everything defaulted except assumption_count
    assert sparse.confidence < real_data.confidence


def test_coverage_gap_always_flagged_as_proxy():
    result = legacy_risk_score(_stable())
    assert result.factor_breakdown["coverage_is_proxy"] is True
    assert result.factor_breakdown["defaulted_signals"]["coverage_gap"] is True


def test_historical_failures_never_scored():
    result = legacy_risk_score(LegacyRiskSignals(failure_count=999))
    assert "failure_count" not in result.factor_breakdown["normalized"]
    assert result.factor_breakdown["historical_failures_omitted"] is True
