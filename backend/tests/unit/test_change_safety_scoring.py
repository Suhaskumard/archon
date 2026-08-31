from archon.analysis.scoring.change_safety import ChangeSafetySignals, change_safety_score


def _safe() -> ChangeSafetySignals:
    return ChangeSafetySignals(
        coverage=0.5, complexity=2, coupling=1, coupling_is_proxy=False,
        centrality=0.02, caller_risk_ratio=0.0, caller_count=2, assumption_count=0, churn=1,
    )


def _dangerous() -> ChangeSafetySignals:
    return ChangeSafetySignals(
        coverage=0.0, complexity=20, coupling=25, coupling_is_proxy=False,
        centrality=0.9, caller_risk_ratio=1.0, caller_count=4, assumption_count=5, churn=80,
    )


def test_safe_component_scores_above_dangerous_component():
    safe = change_safety_score(_safe())
    dangerous = change_safety_score(_dangerous())
    assert safe.score > dangerous.score
    assert safe.category in ("SAFE", "CAUTION")
    assert dangerous.category in ("RISKY", "DANGEROUS")


def test_fully_safe_input_scores_safe():
    result = change_safety_score(
        ChangeSafetySignals(
            coverage=1.0, complexity=0, coupling=0, centrality=0.0,
            caller_risk_ratio=0.0, caller_count=0, assumption_count=0, churn=0,
        )
    )
    assert result.category == "SAFE"
    assert result.score > 90


def test_fully_risky_input_scores_dangerous():
    result = change_safety_score(
        ChangeSafetySignals(
            coverage=0.0, complexity=100, coupling=100, centrality=1.0,
            caller_risk_ratio=1.0, caller_count=10, assumption_count=100, churn=1000,
        )
    )
    assert result.category == "DANGEROUS"
    assert result.score < 10


def test_omitted_signals_never_scored_and_confidence_reflects_it():
    result = change_safety_score(_safe())
    assert "historical_change_success_rate" not in result.factor_breakdown["safe_normalized"]
    assert "historical_failures" not in result.factor_breakdown["safe_normalized"]
    assert result.factor_breakdown["historical_change_success_rate_omitted"] is True
    assert result.factor_breakdown["historical_failures_omitted"] is True
    assert 0.0 <= result.confidence <= 1.0


def test_coverage_always_flagged_as_proxy():
    result = change_safety_score(_safe())
    assert result.factor_breakdown["coverage_is_proxy"] is True
    assert result.factor_breakdown["defaulted_signals"]["coverage"] is True


def test_sign_flip_regression_lower_raw_signal_means_higher_contribution():
    """Complexity/coupling/centrality/caller_risk/churn are all *negative*-direction
    raw signals - a LOWER raw value must yield a HIGHER safety contribution, not lower.
    This is the exact gotcha the sign-flip design has to get right."""
    low_risk = change_safety_score(
        ChangeSafetySignals(
            coverage=0.5, complexity=1, coupling=1, centrality=0.05,
            caller_risk_ratio=0.1, caller_count=1, assumption_count=0, churn=1,
        )
    )
    high_risk = change_safety_score(
        ChangeSafetySignals(
            coverage=0.5, complexity=14, coupling=18, centrality=0.9,
            caller_risk_ratio=0.9, caller_count=1, assumption_count=0, churn=45,
        )
    )
    for factor in ("complexity", "coupling", "centrality", "caller_risk_ratio", "churn"):
        assert (
            low_risk.factor_breakdown["weighted"][factor]
            > high_risk.factor_breakdown["weighted"][factor]
        ), f"{factor} contribution did not decrease as its raw risk increased"
    assert low_risk.score > high_risk.score
