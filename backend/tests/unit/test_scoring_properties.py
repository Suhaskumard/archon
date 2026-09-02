"""Property-based proofs for the four pure scoring engines (spec sections 7, 27-31).

Hand-picked ordering tests live in ``test_{legacy_risk,hotspot,change_safety,
repository_understanding}_scoring.py``; these assert the invariants across the whole
input space: bounded score/confidence, and monotonicity in each signal (with the §7
documented exception - more coverage lowers risk / raises safety).
"""

from __future__ import annotations

import dataclasses

from hypothesis import given
from hypothesis import strategies as st

from archon.analysis.scoring.change_safety import ChangeSafetySignals, change_safety_score
from archon.analysis.scoring.hotspot import HotspotSignals, hotspot_score
from archon.analysis.scoring.legacy_risk import LegacyRiskSignals, legacy_risk_score
from archon.analysis.scoring.understanding import UnderstandingDimensions, understanding_score

_f = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)
_frac = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_n = st.integers(min_value=0, max_value=50)


def _bump(obj, field: str, delta: float):
    cur = getattr(obj, field) or 0.0
    return dataclasses.replace(obj, **{field: cur + delta})


# --- Legacy Risk --------------------------------------------------------------------

_LR_RISK_UP = ("complexity", "churn", "coupling", "debt_score", "age_days")


@given(
    complexity=_f, churn=_f, coverage=_frac, coupling=_f,
    assumption_count=_n, debt_score=_frac, age_days=st.integers(0, 3650),
)
def test_legacy_risk_bounded_and_monotone(**kw):
    base = LegacyRiskSignals(**kw)
    r = legacy_risk_score(base)
    assert 0.0 <= r.score <= 100.0
    assert 0.0 <= r.confidence <= 1.0
    assert r.category in ("LOW", "MODERATE", "HIGH", "CRITICAL")

    for field in _LR_RISK_UP:
        assert legacy_risk_score(_bump(base, field, 25.0)).score >= r.score - 1e-6, field
    # §7 exception: more coverage cannot raise risk
    more_cov = dataclasses.replace(base, coverage=min((base.coverage or 0.0) + 0.3, 1.0))
    assert legacy_risk_score(more_cov).score <= r.score + 1e-6


# --- Hotspot -----------------------------------------------------------------------

_HS_RISK_UP = ("complexity", "churn", "coupling", "debt_score")


@given(
    complexity=_f, churn=_f, coverage=_frac, coupling=_f,
    assumption_count=_n, debt_score=_frac,
)
def test_hotspot_bounded_and_monotone(**kw):
    base = HotspotSignals(**kw)
    r = hotspot_score(base)
    assert 0.0 <= r.score <= 100.0
    assert r.classification in ("STABLE", "WATCH", "RISKY", "CRITICAL")

    for field in _HS_RISK_UP:
        assert hotspot_score(_bump(base, field, 25.0)).score >= r.score - 1e-6, field
    more_cov = dataclasses.replace(base, coverage=min((base.coverage or 0.0) + 0.3, 1.0))
    assert hotspot_score(more_cov).score <= r.score + 1e-6


# --- Change Safety (higher = safer) ----------------------------------------------

_CS_DANGER_UP = ("complexity", "coupling", "centrality", "caller_risk_ratio", "churn")


@given(
    coverage=_frac, complexity=_f, coupling=_f, centrality=_frac,
    caller_risk_ratio=_frac, assumption_count=_n, churn=_f,
)
def test_change_safety_bounded_and_monotone(**kw):
    base = ChangeSafetySignals(**kw)
    r = change_safety_score(base)
    assert 0.0 <= r.score <= 100.0
    assert 0.0 <= r.confidence <= 1.0
    assert r.category in ("SAFE", "CAUTION", "RISKY", "DANGEROUS")

    for field in _CS_DANGER_UP:
        delta = 0.3 if field in ("centrality", "caller_risk_ratio") else 25.0
        assert change_safety_score(_bump(base, field, delta)).score <= r.score + 1e-6, field
    # more coverage cannot lower safety
    more_cov = dataclasses.replace(base, coverage=min(base.coverage + 0.3, 1.0))
    assert change_safety_score(more_cov).score >= r.score - 1e-6


# --- Repository Understanding ---------------------------------------------------

_DIMS = ("architecture", "dependency", "behavior", "historical", "testing", "configuration")


@given(**{d: _frac for d in _DIMS})
def test_understanding_bounded_and_monotone(**kw):
    base = UnderstandingDimensions(**kw)
    r = understanding_score(base)
    assert 0.0 <= r.score <= 100.0
    assert 0.0 <= r.confidence <= 1.0
    for d in _DIMS:
        raised = dataclasses.replace(base, **{d: min(getattr(base, d) + 0.2, 1.0)})
        assert understanding_score(raised).score >= r.score - 1e-6, d
