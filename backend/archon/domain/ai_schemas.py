"""Structured-output schemas for every AI operation (spec sections 13-14).

Rules enforced here + by ``providers/ai/base.py``:

* every AI operation returns one of these pydantic models - never free text;
* every model carries the common envelope (evidence, confidence, classification, ...);
* repository-specific claims must cite an ``EvidenceRef`` that resolves to a real row,
  otherwise the ref is dropped and confidence is floored (hallucination control, section 14);
* malformed output is an error, not something to paper over.

Each schema has a ``*_SCHEMA_VERSION`` constant recorded in ``AnalysisRun.engine_versions``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from archon.domain.enums import Classification, Confidence

BEHAVIOR_SCHEMA_VERSION = "behavior_analysis.v1"
INTENT_SCHEMA_VERSION = "historical_intent.v1"
ASSUMPTION_SCHEMA_VERSION = "assumption_analysis.v1"
TEST_GENERATION_SCHEMA_VERSION = "test_generation.v1"
ROOT_CAUSE_SCHEMA_VERSION = "root_cause_analysis.v1"
PATCH_PROPOSAL_SCHEMA_VERSION = "patch_proposal.v1"
MODERNIZATION_SCHEMA_VERSION = "modernization_recommendation.v1"


class EvidenceRef(BaseModel):
    kind: Literal["component", "commit", "file", "test"]
    ref: str                      # component qualified_name / commit sha / path / test id
    detail: str = ""


class AIEnvelope(BaseModel):
    """Common fields on every AI result (spec section 13)."""

    evidence: list[EvidenceRef] = Field(default_factory=list)
    confidence: Confidence = Confidence.UNKNOWN
    classification: Classification = Classification.INFERENCE
    reasoning_summary: str = ""
    recommended_action: str | None = None


class HistoricalIntent(AIEnvelope):
    """"Why does this exist?" (spec section 25)."""

    likely_purpose: str
    historical_context: str = ""
    current_role: str = ""


class BehaviorAnalysis(AIEnvelope):
    """Interpretation of observed behaviour (spec section 24). Observed != correct."""

    summary: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    likely_invariants: list[str] = Field(default_factory=list)


class AssumptionAnalysis(AIEnvelope):
    """Interpretation of one detected hidden assumption (spec section 26)."""

    kind: str
    description: str
    risk: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    suggested_test: str = ""


class TestScenario(BaseModel):
    """One proposed test case for a target component (spec section 33)."""

    kind: Literal["UNIT", "BOUNDARY", "INVALID_INPUT", "EXCEPTION", "REGRESSION", "INTEGRATION"]
    description: str
    input_args: dict = Field(default_factory=dict)
    expected_behavior: str  # "returns", "raises", or free text


class TestGeneration(AIEnvelope):
    """Proposed test scenarios for an untested target (spec sections 33, 35).

    Every scenario is static- and sandbox-validated by ``testing/generation.py`` before
    it counts - this schema only proposes, it never certifies.
    """

    target_component: str  # component id
    scenarios: list[TestScenario] = Field(default_factory=list)


class RootCauseHypothesis(BaseModel):
    """One ranked root-cause hypothesis (spec section 38)."""

    statement: str
    confidence: Confidence = Confidence.UNKNOWN
    evidence: list[EvidenceRef] = Field(default_factory=list)


class RootCauseAnalysis(AIEnvelope):
    """Root-cause investigation of one test failure (spec section 38).

    Proceeds to healing only when the top hypothesis clears a documented confidence
    threshold - see ``investigation/engine.py``. A failure pattern the mock provider
    doesn't recognize yields an empty hypothesis list and ``confidence=UNKNOWN``, never
    a fabricated guess.
    """

    summary: str
    hypotheses: list[RootCauseHypothesis] = Field(default_factory=list)
    recommended_verification: list[str] = Field(default_factory=list)


class PatchProposal(AIEnvelope):
    """One candidate fix under the Minimal Patch Principle (spec section 39).

    ``old_snippet``/``new_snippet`` are exact source text - the caller applies them as
    a literal string replacement (never a fuzzy/AI-applied edit) and computes the real
    unified diff itself, so "applies cleanly" is a verifiable fact, not a claim.
    """

    strategy: str
    target_component: str  # component id
    target_file: str
    old_snippet: str
    new_snippet: str
    rationale: str = ""


class ModernizationItem(BaseModel):
    """One recommended modernization action for a single target (spec section 46)."""

    target: str  # component qualified_name, or an architecture-area label (e.g. an import cycle)
    strategy: Literal[
        "add_tests", "extract_dependency", "refactor", "replace_dependency", "rewrite"
    ]
    risk: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    effort: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    impact: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    rationale: str = ""
    required_tests: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ModernizationRecommendation(AIEnvelope):
    """A prioritized modernization plan for the repository (spec section 46).

    The AI only picks the strategy/risk/effort/impact/rationale per target from the
    deterministic findings it is handed - it never invents targets, and it never
    prefers ``rewrite`` when a cheaper safe option applies (Principle 12). The safe
    *ordering* of these items is computed deterministically by
    ``archon/modernization/planner.py``, not here.
    """

    recommendations: list[ModernizationItem] = Field(default_factory=list)


SCHEMA_VERSIONS: dict[str, str] = {
    "historical_intent": INTENT_SCHEMA_VERSION,
    "behavior_analysis": BEHAVIOR_SCHEMA_VERSION,
    "assumption_analysis": ASSUMPTION_SCHEMA_VERSION,
    "test_generation": TEST_GENERATION_SCHEMA_VERSION,
    "root_cause_analysis": ROOT_CAUSE_SCHEMA_VERSION,
    "patch_proposal": PATCH_PROPOSAL_SCHEMA_VERSION,
    "modernization_recommendation": MODERNIZATION_SCHEMA_VERSION,
}

__all__ = [
    "EvidenceRef",
    "AIEnvelope",
    "HistoricalIntent",
    "BehaviorAnalysis",
    "AssumptionAnalysis",
    "TestScenario",
    "TestGeneration",
    "RootCauseHypothesis",
    "RootCauseAnalysis",
    "PatchProposal",
    "SCHEMA_VERSIONS",
    "INTENT_SCHEMA_VERSION",
    "BEHAVIOR_SCHEMA_VERSION",
    "ASSUMPTION_SCHEMA_VERSION",
    "TEST_GENERATION_SCHEMA_VERSION",
    "ROOT_CAUSE_SCHEMA_VERSION",
    "PATCH_PROPOSAL_SCHEMA_VERSION",
]
