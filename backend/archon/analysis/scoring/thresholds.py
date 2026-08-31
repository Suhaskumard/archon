"""Versioned weights/thresholds for the Phase 5 scoring engines (spec sections 27-30).

Every magic number the scoring engines use lives here so a future version bump touches
one file. Changing a value here should bump the relevant ``*_VERSION`` constant in its
engine module.
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

# --- Repository Understanding weights (understanding.v1, spec sec 30) ---------------
UNDERSTANDING_DIMENSION_WEIGHTS: dict[str, float] = {
    "architecture": 1.0,
    "dependency": 1.0,
    "behavior": 1.0,
    "historical": 1.0,
    "testing": 1.0,
    "configuration": 1.0,
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
