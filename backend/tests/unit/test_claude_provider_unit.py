"""ClaudeAIProvider with a fake injected client - no network, no `anthropic` needed."""

from __future__ import annotations

import pytest

from archon.domain.ai_schemas import AssumptionAnalysis
from archon.providers.ai import drain_ai_calls, get_ai_provider
from archon.providers.ai.base import AIOutputError, AIProviderError
from archon.providers.ai.claude import ClaudeAIProvider

_GOOD = {
    "kind": "division",
    "description": "divides without guarding a zero divisor",
    "risk": "HIGH",
    "suggested_test": "call with divisor=0 and assert no ZeroDivisionError",
    "evidence": [{"kind": "component", "ref": "pkg.mod.f", "detail": "subject"}],
    "confidence": "MEDIUM",
    "classification": "HYPOTHESIS",
    "reasoning_summary": "matched a division hidden-assumption",
}

_CTX = {
    "assumption": {"kind": "division", "description": "d", "location": "m.py:1"},
    "component": {"qualified_name": "pkg.mod.f", "path": "pkg/mod.py", "git": {}},
    "tests": [],
    "known_refs": {"component": {"pkg.mod.f"}},
}


class _Usage:
    def __init__(self, i, o):
        self.input_tokens, self.output_tokens = i, o


class _Block:
    type = "tool_use"

    def __init__(self, data):
        self.input = data


class _Resp:
    def __init__(self, data):
        self.content = [_Block(data)]
        self.usage = _Usage(11, 22)


class _NoToolResp:
    content: list = []
    usage = _Usage(1, 2)


class _HttpErr(Exception):
    def __init__(self, status):
        super().__init__(f"http {status}")
        self.status_code = status


class _FakeClient:
    def __init__(self, *, results=None):
        self.messages = self
        self._results = list(results or [])
        self.calls = 0

    def create(self, **_kw):
        self.calls += 1
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _provider(client) -> ClaudeAIProvider:
    return ClaudeAIProvider(client=client)


def test_generate_returns_tool_use_dict_and_validates():
    p = _provider(_FakeClient(results=[_Resp(_GOOD)]))
    result = p.complete_structured("assumption_analysis", AssumptionAnalysis, _CTX)
    assert isinstance(result, AssumptionAnalysis)
    assert result.risk == "HIGH"


def test_inherited_evidence_control_drops_fabricated_ref():
    bad = {**_GOOD, "evidence": [{"kind": "component", "ref": "ghost.thing", "detail": "x"}],
           "confidence": "HIGH"}
    p = _provider(_FakeClient(results=[_Resp(bad)]))
    result = p.complete_structured("assumption_analysis", AssumptionAnalysis, _CTX)
    assert result.evidence == []
    assert result.confidence.value in ("LOW", "UNKNOWN")


def test_no_tool_use_block_raises_ai_output_error():
    p = _provider(_FakeClient(results=[_NoToolResp()]))
    with pytest.raises(AIOutputError):
        p.complete_structured("assumption_analysis", AssumptionAnalysis, _CTX)


def test_bad_request_maps_to_ai_output_error():
    p = _provider(_FakeClient(results=[_HttpErr(400)]))
    with pytest.raises(AIOutputError):
        p.complete_structured("assumption_analysis", AssumptionAnalysis, _CTX)


def test_auth_error_maps_to_provider_error():
    p = _provider(_FakeClient(results=[_HttpErr(401)]))
    with pytest.raises(AIProviderError):
        p.complete_structured("assumption_analysis", AssumptionAnalysis, _CTX)


def test_transient_errors_retry_then_recover(monkeypatch):
    monkeypatch.setattr("archon.providers.ai.claude.time.sleep", lambda _s: None)
    client = _FakeClient(results=[_HttpErr(503), _HttpErr(503), _Resp(_GOOD)])
    p = _provider(client)
    p._max_retries = 2
    result = p.complete_structured("assumption_analysis", AssumptionAnalysis, _CTX)
    assert isinstance(result, AssumptionAnalysis)
    assert client.calls == 3


def test_transient_errors_exhaust_retries(monkeypatch):
    monkeypatch.setattr("archon.providers.ai.claude.time.sleep", lambda _s: None)
    p = _provider(_FakeClient(results=[_HttpErr(503), _HttpErr(503), _HttpErr(503)]))
    p._max_retries = 2
    with pytest.raises(AIProviderError):
        p.complete_structured("assumption_analysis", AssumptionAnalysis, _CTX)


def test_clip_context_shrinks_over_budget_payload():
    p = _provider(_FakeClient(results=[]))
    p._max_context_chars = 300
    payload = {"targets": [{"qualified_name": f"pkg.mod.f{i}"} for i in range(200)]}
    clipped = p._clip_context(payload)
    import json

    assert len(json.dumps(clipped)) <= 300
    assert len(clipped["targets"]) < 200


def test_tool_input_schema_is_strict_object_without_titles():
    schema = ClaudeAIProvider._tool_input_schema(AssumptionAnalysis)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "title" not in schema


def test_ai_call_recorded_for_claude_not_for_mock():
    drain_ai_calls()
    _provider(_FakeClient(results=[_Resp(_GOOD)])).complete_structured(
        "assumption_analysis", AssumptionAnalysis, _CTX
    )
    recs = drain_ai_calls()
    assert len(recs) == 1 and recs[0].operation == "assumption_analysis"
    assert recs[0].provider == "claude"

    get_ai_provider().complete_structured("assumption_analysis", AssumptionAnalysis, _CTX)
    assert drain_ai_calls() == []
