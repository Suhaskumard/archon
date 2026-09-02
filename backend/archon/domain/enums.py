"""Enumerations for the ARCHON domain (spec sections 4, 10, 15, 17)."""

from __future__ import annotations

import enum


class Classification(str, enum.Enum):
    """Every stored conclusion is tagged with one of these (spec section 4)."""

    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"


class Confidence(str, enum.Enum):
    """Confidence attached to an AI conclusion (spec sections 4, 13-14)."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"

    @property
    def score(self) -> float:
        return {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3, "UNKNOWN": 0.0}[self.value]


class RiskLevel(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ProviderKind(str, enum.Enum):
    LOCAL = "LOCAL"
    GITHUB = "GITHUB"


class ComponentKind(str, enum.Enum):
    """Source-code entities extracted in Phase 2 (spec section 22)."""

    FILE = "FILE"
    MODULE = "MODULE"
    CLASS = "CLASS"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"


class DependencyKind(str, enum.Enum):
    """Edges between components / modules (spec sections 22-23).

    Phase 2 populates CONTAINS/IMPORTS/CALLS/INHERITS; Phase 3 adds module-level
    DEPENDS_ON and TESTED_BY. The remaining kinds are declared now so the vocabulary is
    stable for the whole project and are populated by their phase (git = Phase 4,
    failures/patches = Phase 9).
    """

    CONTAINS = "CONTAINS"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    DEPENDS_ON = "DEPENDS_ON"
    TESTED_BY = "TESTED_BY"
    CHANGED_BY = "CHANGED_BY"
    CHANGED_WITH = "CHANGED_WITH"
    FAILED_IN = "FAILED_IN"
    FIXED_BY = "FIXED_BY"
    AFFECTS = "AFFECTS"


class RiskCategory(str, enum.Enum):
    """Legacy Risk score bucket (spec section 27)."""

    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ChangeSafetyCategory(str, enum.Enum):
    """Change Safety score bucket (spec sections 31-32).

    Higher score = safer - the inverse sense of RiskCategory/HotspotClassification
    (see analysis/scoring/change_safety.py for the sign-flip handling).
    """

    SAFE = "SAFE"
    CAUTION = "CAUTION"
    RISKY = "RISKY"
    DANGEROUS = "DANGEROUS"


class HotspotClassification(str, enum.Enum):
    """Hotspot score bucket (spec section 29)."""

    STABLE = "STABLE"
    WATCH = "WATCH"
    RISKY = "RISKY"
    CRITICAL = "CRITICAL"


class TechDebtCategory(str, enum.Enum):
    """Technical-debt finding category (spec section 28)."""

    LONG_FUNCTION = "LONG_FUNCTION"
    LARGE_CLASS = "LARGE_CLASS"
    DUPLICATE_LOGIC = "DUPLICATE_LOGIC"
    CIRCULAR_DEPENDENCY = "CIRCULAR_DEPENDENCY"
    HIGH_COUPLING = "HIGH_COUPLING"
    LOW_COHESION = "LOW_COHESION"
    DEAD_CODE_CANDIDATE = "DEAD_CODE_CANDIDATE"
    DEPRECATED_API = "DEPRECATED_API"
    HARDCODED_CONFIG = "HARDCODED_CONFIG"
    BROAD_EXCEPT = "BROAD_EXCEPT"
    SILENT_FAILURE = "SILENT_FAILURE"
    GLOBAL_STATE = "GLOBAL_STATE"
    MAGIC_NUMBER = "MAGIC_NUMBER"


class TechDebtSeverity(str, enum.Enum):
    """Technical-debt finding severity (spec section 28)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TestCaseKind(str, enum.Enum):
    """Kind of test case (spec section 33). Only EXISTING is populated in Phase 7;
    the rest are declared now for the vocabulary Phase 8's characterization/generation
    will populate."""

    EXISTING = "EXISTING"
    CHARACTERIZATION = "CHARACTERIZATION"
    UNIT = "UNIT"
    BOUNDARY = "BOUNDARY"
    INVALID_INPUT = "INVALID_INPUT"
    EXCEPTION = "EXCEPTION"
    REGRESSION = "REGRESSION"
    INTEGRATION = "INTEGRATION"


class TestCaseOrigin(str, enum.Enum):
    """Where a test case came from (spec section 33)."""

    DISCOVERED = "DISCOVERED"
    AI = "AI"
    CHARACTERIZATION = "CHARACTERIZATION"


class ExecutionKind(str, enum.Enum):
    """What a sandbox execution ran (spec sections 12, 33, 36, 39, 41).

    Only EXISTING_TESTS is produced in Phase 7; the rest are declared now for Phases
    8-9 (characterization, generated tests, patch verification, regression).
    """

    EXISTING_TESTS = "EXISTING_TESTS"
    CHARACTERIZATION = "CHARACTERIZATION"
    GENERATED_TESTS = "GENERATED_TESTS"
    PATCH_VERIFICATION = "PATCH_VERIFICATION"
    REGRESSION = "REGRESSION"


class TestGapKind(str, enum.Enum):
    """Kind of test-gap finding (spec sections 33-35)."""

    UNTESTED_FUNCTION = "UNTESTED_FUNCTION"
    MISSING_EDGE_CASE = "MISSING_EDGE_CASE"
    MISSING_EXCEPTION_TEST = "MISSING_EXCEPTION_TEST"
    MISSING_REGRESSION_TEST = "MISSING_REGRESSION_TEST"
    MISSING_CHARACTERIZATION = "MISSING_CHARACTERIZATION"


class TestGapPriority(str, enum.Enum):
    """Test-gap priority bucket, ranked by Legacy Risk / Change Safety (spec section 35)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PatchState(str, enum.Enum):
    """Patch lifecycle (spec sections 39-42)."""

    PROPOSED = "PROPOSED"
    TESTING = "TESTING"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class VerificationVerdict(str, enum.Enum):
    """Terminal outcome of patch verification (spec section 41)."""

    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class SupportLevel(str, enum.Enum):
    """MVP supported-repository contract (spec section 17)."""

    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class RunMode(str, enum.Enum):
    FULL = "FULL"  # the whole closed loop through MODERNIZING - needs the Docker sandbox
    ANALYSIS_ONLY = "ANALYSIS_ONLY"  # deterministic analysis + scoring + test discovery; no execution / healing / modernization (sandbox-free)
    INGEST_ONLY = "INGEST_ONLY"  # clone + snapshot only


class Stage(str, enum.Enum):
    """Analysis pipeline stages (spec sections 10, 67).

    Phase 1 implements INGESTING and SNAPSHOTTING; the remaining stages are declared now
    so the state machine is complete and unambiguous, and are wired up in later phases.
    """

    INGESTING = "INGESTING"
    SNAPSHOTTING = "SNAPSHOTTING"
    ANALYZING_SOURCE = "ANALYZING_SOURCE"
    ANALYZING_GIT = "ANALYZING_GIT"
    BUILDING_GRAPH = "BUILDING_GRAPH"
    RECONSTRUCTING_ARCHITECTURE = "RECONSTRUCTING_ARCHITECTURE"
    ARCHAEOLOGIZING = "ARCHAEOLOGIZING"
    SCORING_UNDERSTANDING = "SCORING_UNDERSTANDING"
    BUILDING_LEGACY_DNA = "BUILDING_LEGACY_DNA"
    ANALYZING_TECH_DEBT = "ANALYZING_TECH_DEBT"
    SCORING_HOTSPOTS = "SCORING_HOTSPOTS"
    ASSESSING_CHANGE_SAFETY = "ASSESSING_CHANGE_SAFETY"
    ANALYZING_CHANGE_IMPACT = "ANALYZING_CHANGE_IMPACT"
    ANALYZING_TESTS = "ANALYZING_TESTS"
    CHARACTERIZING = "CHARACTERIZING"
    GENERATING_TESTS = "GENERATING_TESTS"
    EXECUTING = "EXECUTING"
    DETECTING_FAILURES = "DETECTING_FAILURES"
    INVESTIGATING = "INVESTIGATING"
    GENERATING_PATCH = "GENERATING_PATCH"
    RANKING_PATCHES = "RANKING_PATCHES"
    VERIFYING_PATCH = "VERIFYING_PATCH"
    REGRESSION_VERIFYING = "REGRESSION_VERIFYING"
    RECORDING_INCIDENT = "RECORDING_INCIDENT"
    MODERNIZING = "MODERNIZING"


class ModernizationStrategy(str, enum.Enum):
    """How to modernize one target (spec section 46). No automatic preference for
    REWRITE - it is only chosen when no cheaper safe option applies (Principle 12)."""

    ADD_TESTS = "ADD_TESTS"
    EXTRACT_DEPENDENCY = "EXTRACT_DEPENDENCY"
    REFACTOR = "REFACTOR"
    REPLACE_DEPENDENCY = "REPLACE_DEPENDENCY"
    REWRITE = "REWRITE"


class RunState(str, enum.Enum):
    """Analysis run lifecycle (spec section 10)."""

    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobState(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobType(str, enum.Enum):
    ANALYSIS = "ANALYSIS"
