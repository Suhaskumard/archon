from archon.analysis.scoring.hotspot import HotspotSignals, hotspot_score


def test_stable_component_is_stable():
    result = hotspot_score(HotspotSignals(complexity=1, churn=0, coverage=0.9, coupling=1, debt_score=0.0))
    assert result.classification == "STABLE"


def test_overlap_bonus_fires_at_three_elevated_signals():
    # complexity, churn, coupling all elevated -> overlap bonus applies
    with_overlap = hotspot_score(
        HotspotSignals(complexity=14, churn=45, coverage=0.5, coupling=18, debt_score=0.0)
    )
    assert with_overlap.reasons["overlap_bonus_applied"] is True
    assert len(with_overlap.reasons["elevated_signals"]) >= 3


def test_no_overlap_bonus_below_three_signals():
    result = hotspot_score(HotspotSignals(complexity=14, churn=0, coverage=1.0, coupling=0, debt_score=0.0))
    assert result.reasons["overlap_bonus_applied"] is False


def test_risky_component_ranks_above_stable():
    stable = hotspot_score(HotspotSignals(complexity=1, churn=0, coverage=0.9, coupling=1, debt_score=0.0))
    risky = hotspot_score(
        HotspotSignals(complexity=20, churn=80, coverage=0.0, coupling=25, assumption_count=5, debt_score=1.0)
    )
    assert risky.score > stable.score
    assert risky.classification in ("RISKY", "CRITICAL")
