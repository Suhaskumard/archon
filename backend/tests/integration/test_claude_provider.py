"""Live Claude provider - gated on ANTHROPIC_API_KEY + archon[claude], skips like Docker."""

from __future__ import annotations

import pytest

from archon.config import reset_settings_cache
from archon.domain.ai_schemas import AssumptionAnalysis
from archon.providers.ai import get_ai_provider, reset_ai_provider_cache

_CTX = {
    "assumption": {
        "kind": "division",
        "description": "price_for divides total by quantity without guarding zero",
        "location": "pricing/engine.py:42",
    },
    "component": {
        "qualified_name": "pricing.engine.price_for",
        "path": "pricing/engine.py",
        "git": {"commit_count": 6, "age_days": 400},
    },
    "tests": [],
    "known_refs": {"component": {"pricing.engine.price_for"}, "file": {"pricing/engine.py"}},
}


@pytest.mark.parametrize("_run", [1])
def test_live_assumption_analysis_is_schema_valid_and_evidence_checked(
    anthropic_api_key_available, monkeypatch, _run
):
    monkeypatch.setenv("ARCHON_AI_PROVIDER", "claude")
    reset_settings_cache()
    reset_ai_provider_cache()
    try:
        ai = get_ai_provider()
        assert ai.name == "claude"
        result = ai.complete_structured("assumption_analysis", AssumptionAnalysis, _CTX)
        assert isinstance(result, AssumptionAnalysis)
        assert result.risk in ("HIGH", "MEDIUM", "LOW")
        assert result.suggested_test
        for ref in result.evidence:
            pool = _CTX["known_refs"].get(ref.kind)
            assert pool is None or ref.ref in pool
    finally:
        monkeypatch.delenv("ARCHON_AI_PROVIDER", raising=False)
        reset_settings_cache()
        reset_ai_provider_cache()
