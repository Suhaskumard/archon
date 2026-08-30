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


SCHEMA_VERSIONS: dict[str, str] = {
    "historical_intent": INTENT_SCHEMA_VERSION,
    "behavior_analysis": BEHAVIOR_SCHEMA_VERSION,
    "assumption_analysis": ASSUMPTION_SCHEMA_VERSION,
}

__all__ = [
    "EvidenceRef",
    "AIEnvelope",
    "HistoricalIntent",
    "BehaviorAnalysis",
    "AssumptionAnalysis",
    "SCHEMA_VERSIONS",
    "INTENT_SCHEMA_VERSION",
    "BEHAVIOR_SCHEMA_VERSION",
    "ASSUMPTION_SCHEMA_VERSION",
]
