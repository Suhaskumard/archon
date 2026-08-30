"""Enumerations for the ARCHON domain (spec sections 4, 10, 15, 17)."""

from __future__ import annotations

import enum


class Classification(str, enum.Enum):
    """Every stored conclusion is tagged with one of these (spec section 4)."""

    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"


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
    """Edges between components (spec sections 22-23)."""

    CONTAINS = "CONTAINS"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    DEPENDS_ON = "DEPENDS_ON"


class SupportLevel(str, enum.Enum):
    """MVP supported-repository contract (spec section 17)."""

    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class RunMode(str, enum.Enum):
    FULL = "FULL"            # the whole closed loop
    ANALYSIS_ONLY = "ANALYSIS_ONLY"
    INGEST_ONLY = "INGEST_ONLY"  # Phase 1 default until later phases land


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
