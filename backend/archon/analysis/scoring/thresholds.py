"""Versioned weights/thresholds for the scoring engines (spec sections 27-32).

Every magic number the scoring engines use lives here so a future version bump touches
one file. Changing a value here should bump the relevant ``*_VERSION`` constant in its
engine module.

Calibration basis
-----------------
The scales are set so a value "as bad as anything we expect to see in a normal Python
repo" normalizes to ~1.0. They are pinned to observable outcomes by
``tests/acceptance/test_scoring_calibration.py``, which scores the two fixture repos and
asserts each planted component lands in its intended bucket - so a scale change that
mis-ranks a fixture fails a test rather than silently drifting.

* ``COMPLEXITY_SCALE = 15`` - the scoring fixture's deliberately-gnarly
  ``pricing_engine.price_for`` (deep nested tier/region branching) sits at cyclomatic
  ~12; 15 is "a function you would not want to change without tests".
* ``CHURN_SCALE = 50`` - lines changed across the analyzed history; a file rewritten a
  few times over a project's life reaches this.
* ``COUPLING_SCALE = 20`` (fan_in + fan_out) - ``pricing_engine`` has fan_in 4 by
  design; a module 4-5 other modules import *and* that imports several is genuinely
  central at ~20.
* ``AGE_SCALE_DAYS = 730`` - two years; older code carries more accumulated assumptions.
* ``ASSUMPTION_COUNT_SCALE = 5`` - five hidden-assumption findings on one component is a
  lot.
* ``DEBT_SCORE_MAX = 20`` - the weighted-severity sum (LOW 1 / MED 2 / HIGH 4 / CRIT 8)
  at which ``debt_score`` saturates: e.g. five HIGH-severity findings.
"""

from __future__ import annotations

# --- normalization scales (a signal at/above its scale normalizes to ~1.0) -----------
COMPLEXITY_SCALE = 15.0
CHURN_SCALE = 50.0
AGE_SCALE_DAYS = 365.0 * 2
COUPLING_SCALE = 20.0  # fan_in + fan_out
ASSUMPTION_COUNT_SCALE = 5.0

# --- Legacy Risk weights (legacy_risk.v1) --------------------------------------------
# Weighted so churn + complexity + low coverage dominate (spec sec 7).
LEGACY_RISK_WEIGHTS: dict[str, float] = {
    "complexity": 0.20,
    "churn": 0.20,
    "coverage_gap": 0.20,
    "coupling": 0.10,
    "assumption_count": 0.10,
    "debt_score": 0.10,
    "age": 0.10,
}
# score >= HIGH -> CRITICAL; >= MODERATE -> HIGH; >= LOW -> MODERATE; else LOW.
LEGACY_RISK_THRESHOLDS: dict[str, float] = {"LOW": 25.0, "MODERATE": 50.0, "HIGH": 75.0}

# --- Hotspot weights + "signals overlap" bonus (hotspot.v1, spec sec 29) ------------
HOTSPOT_WEIGHTS: dict[str, float] = {
    "complexity": 0.20,
    "churn": 0.25,
    "coupling": 0.15,
    "coverage_gap": 0.15,
    "assumption_count": 0.10,
    "debt_score": 0.15,
}
HOTSPOT_OVERLAP_SIGNAL_THRESHOLD = 0.6  # a normalized signal counts as "elevated" above this
HOTSPOT_OVERLAP_MIN_SIGNALS = 3
HOTSPOT_OVERLAP_BONUS = 1.15
HOTSPOT_THRESHOLDS: dict[str, float] = {"STABLE": 25.0, "WATCH": 50.0, "RISKY": 75.0}

# --- Repository Understanding weights (understanding.v2, spec sec 30) ---------------
# Non-uniform (v2): weighted toward the dimensions that most determine whether you can
# safely *change* the code. Architecture + behaviour + testing understanding matter more
# than configuration parsing; historical depth is useful context but secondary.
UNDERSTANDING_DIMENSION_WEIGHTS: dict[str, float] = {
    "architecture": 1.5,
    "behavior": 1.3,
    "testing": 1.3,
    "dependency": 1.0,
    "historical": 0.8,
    "configuration": 0.6,
}
UNDERSTANDING_HISTORY_DEPTH_DAYS = 180.0  # git span at/above this -> full historical score

# --- tech-debt detector thresholds (tech_debt.v1, spec sec 28) ----------------------
LONG_FUNCTION_LOC = 50
LARGE_CLASS_LOC = 200
LARGE_CLASS_METHOD_COUNT = 15
HIGH_COUPLING_FAN_TOTAL = 10
DUPLICATE_LOGIC_MIN_NODES = 12  # ast.walk() node count floor before comparing structure
LOW_COHESION_MIN_METHODS = 3
MAGIC_NUMBER_ALLOWED = {0, 1, -1}

CATEGORY_DEFAULT_SEVERITY: dict[str, str] = {
    "LONG_FUNCTION": "LOW",
    "LARGE_CLASS": "LOW",
    "DUPLICATE_LOGIC": "MEDIUM",
    "CIRCULAR_DEPENDENCY": "HIGH",
    "HIGH_COUPLING": "MEDIUM",
    "LOW_COHESION": "MEDIUM",
    "DEAD_CODE_CANDIDATE": "LOW",
    "DEPRECATED_API": "MEDIUM",
    "HARDCODED_CONFIG": "HIGH",
    "BROAD_EXCEPT": "HIGH",
    "SILENT_FAILURE": "HIGH",
    "GLOBAL_STATE": "MEDIUM",
    "MAGIC_NUMBER": "LOW",
}
SEVERITY_WEIGHT: dict[str, int] = {"LOW": 1, "MEDIUM": 2, "HIGH": 4, "CRITICAL": 8}
DEBT_SCORE_MAX = 20.0  # weighted-severity sum that normalizes debt_score to 1.0

# Legacy Risk cannot wait for the full 13-detector ANALYZING_TECH_DEBT pass (fixed stage
# order runs BUILDING_LEGACY_DNA first) - it computes this cheap subset internally instead.
# See analysis/scoring/legacy_dna.py.
LEGACY_RISK_DEBT_SUBSET = (
    "LONG_FUNCTION", "LARGE_CLASS", "CIRCULAR_DEPENDENCY", "HIGH_COUPLING",
)

# --- Change Safety weights (change_safety.v1, spec sec 31) --------------------------
# Higher score = safer (the inverse sense of Legacy Risk/Hotspot) - every negative-
# direction signal is inverted (1 - normalized) before weighting; see change_safety.py.
CHANGE_SAFETY_WEIGHTS: dict[str, float] = {
    "coverage": 0.20,
    "complexity": 0.15,
    "coupling": 0.15,
    "centrality": 0.15,
    "caller_risk_ratio": 0.20,
    "assumption_count": 0.05,
    "churn": 0.10,
}
# score >= CAUTION -> SAFE; >= RISKY -> CAUTION; >= DANGEROUS -> RISKY; else DANGEROUS.
CHANGE_SAFETY_THRESHOLDS: dict[str, float] = {"DANGEROUS": 25.0, "RISKY": 50.0, "CAUTION": 75.0}
CENTRALITY_SCALE = 1.0  # betweenness_centrality is already in [0, 1]
# a normalized safe_norm below this is "elevated concern" for recommended_preparation
CHANGE_SAFETY_CONCERN_THRESHOLD = 0.5
