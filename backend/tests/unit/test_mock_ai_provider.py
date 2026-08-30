"""MockAIProvider: deterministic, schema-valid, hallucination-controlled (spec 13-14)."""

from __future__ import annotations

import pytest

from archon.domain.ai_schemas import AssumptionAnalysis, BehaviorAnalysis, HistoricalIntent
from archon.domain.enums import Confidence
from archon.providers.ai import get_ai_provider
from archon.providers.ai.base import AIOutputError, AIProvider
from archon.providers.ai.mock import MockAIProvider


def test_provider_selection_defaults_to_mock():
    assert isinstance(get_ai_provider(), MockAIProvider)


def test_historical_intent_is_deterministic():
    p = MockAIProvider()
    ctx = {
        "component": {"qualified_name": "a.b", "name": "b", "role": "domain",
                      "docstring": "Does the thing.",
                      "git": {"commit_count": 2, "age_days": 30, "distinct_authors": 1}},
        "callers": ["a.c"], "tests": [],
        "known_refs": {"component": {"a.b"}},
    }
    r1 = p.complete_structured("historical_intent", HistoricalIntent, ctx)
    r2 = p.complete_structured("historical_intent", HistoricalIntent, ctx)
    assert r1.model_dump() == r2.model_dump()
    assert r1.likely_purpose == "Does the thing."
    assert r1.confidence is Confidence.MEDIUM
    assert r1.evidence and r1.evidence[0].ref == "a.b"


def test_unresolved_evidence_ref_is_dropped_and_confidence_floored():
    p = MockAIProvider()
    ctx = {
        "component": {"qualified_name": "ghost.module", "name": "module", "role": "domain",
                      "docstring": "x", "git": {"commit_count": 5}},
        "callers": [], "tests": [], "commit_refs": ["deadbeef"],
        "known_refs": {"component": {"real.only"}, "commit": set()},
    }
    r = p.complete_structured("historical_intent", HistoricalIntent, ctx)
    # ghost.module + deadbeef are not in known_refs -> dropped, confidence floored
    assert all(e.ref in {"real.only"} for e in r.evidence)
    assert r.confidence in (Confidence.LOW, Confidence.UNKNOWN)


def test_assumption_risk_weighting():
    p = MockAIProvider()
    base = {
        "assumption": {"kind": "division", "description": "d", "location": "m.py:1"},
        "component": {"qualified_name": "a.b", "path": "a/b.py", "git": {"commit_count": 1}},
        "known_refs": {"component": {"a.b"}, "file": {"a/b.py"}},
    }
    low = p.complete_structured("assumption_analysis", AssumptionAnalysis, {**base, "tests": ["t"]})
    high = p.complete_structured(
        "assumption_analysis", AssumptionAnalysis,
        {**base, "tests": [], "component": {**base["component"], "git": {"commit_count": 3}}},
    )
    assert low.risk == "MEDIUM"          # base division risk
    assert high.risk == "HIGH"           # + churn + untested
    assert high.suggested_test           # non-empty templated test


def test_behavior_analysis_echoes_facts():
    p = MockAIProvider()
    r = p.complete_structured(
        "behavior_analysis", BehaviorAnalysis,
        {"component": {"qualified_name": "a.f", "name": "f"},
         "inputs": ["x", "y"], "outputs": ["int"], "side_effects": ["writes _CACHE"],
         "likely_invariants": ["x >= 0"], "known_refs": {"component": {"a.f"}}},
    )
    assert r.inputs == ["x", "y"] and r.outputs == ["int"]
    assert "writes _CACHE" in r.side_effects
    assert "f accepts x and y" in r.summary


def test_malformed_output_raises_ai_output_error():
    class BadProvider(AIProvider):
        name = "bad"

        def _generate(self, operation, schema, context):
            return {"not": "a valid HistoricalIntent"}

    with pytest.raises(AIOutputError):
        BadProvider().complete_structured("historical_intent", HistoricalIntent, {})
