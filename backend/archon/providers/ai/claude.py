"""Real Anthropic-backed AI provider (spec sections 13-14, 18).

The driver behind the ``AIProvider`` ABC. It only implements ``_generate`` - the base
class still does pydantic validation and the ``_validate_evidence`` hallucination control
(drop unresolved refs, floor confidence). Structured output is forced with a single
Anthropic *tool* whose ``input_schema`` is the operation's pydantic JSON schema; Claude
must call it, so the raw result is already schema-shaped.

The mock provider stays the default (``ARCHON_AI_PROVIDER`` unset / ``mock``); this driver
is only constructed when ``ARCHON_AI_PROVIDER=claude`` and needs ``archon[claude]`` plus a
key. Every call is transient-retried, timeout-bounded, token-budget-clipped, and recorded
(via the base ``AICallRecord`` buffer) so the orchestrator can write a
``produced_by="claude:<model>"`` Evidence row.
"""

from __future__ import annotations

import json
import random
import time
from typing import Any

from pydantic import BaseModel

from archon.config import Settings, get_settings
from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.logging import get_logger
from archon.providers.ai.base import AIOutputError, AIProvider, AIProviderError

try:  # optional dependency - only needed for ARCHON_AI_PROVIDER=claude
    import anthropic
except ModuleNotFoundError:  # pragma: no cover - exercised on a mock-only install
    anthropic = None  # type: ignore[assignment]

log = get_logger("archon.ai.claude")

# HTTP statuses worth retrying (transient / rate limit / overloaded).
_RETRY_STATUS = frozenset({408, 409, 429, 500, 502, 503, 529})

_LIST_CLIP_PRIORITY = (
    "targets", "callers", "callees", "commit_refs", "historical_incidents",
    "assumptions", "tests", "inputs", "outputs", "side_effects", "likely_invariants",
)

_SYSTEM_BASE = (
    "You are ARCHON's interpretation layer. Deterministic engines have already extracted "
    "every repository fact; you only classify and phrase what you are given. Call the "
    "provided tool exactly once with a value that matches its schema. Every "
    "`evidence[].ref` you emit MUST appear verbatim in the `known_refs` lists in the user "
    "message - never invent a component, file, commit, symbol, or line number. If the "
    "evidence does not support a conclusion, say so and set `confidence` to LOW or "
    "UNKNOWN; do not guess."
)

_OP_RULES: dict[str, str] = {
    "historical_intent": (
        " Task: explain why this component exists and its role now. Set "
        "`classification` to INFERENCE only when a docstring or behaviour signal supports "
        "it, otherwise HYPOTHESIS. If `tests` is empty, recommend adding characterization "
        "tests before any change."
    ),
    "behavior_analysis": (
        " Task: summarise the component's *observed* behaviour (observed is not the same "
        "as correct). Echo the provided input/output/side-effect/invariant lists unless "
        "the evidence contradicts them."
    ),
    "assumption_analysis": (
        " Task: rate one detected hidden assumption. Derive `risk` from the assumption "
        "kind, raised by churn and by missing tests. Give one concrete `suggested_test` "
        "that would violate the assumption."
    ),
    "test_generation": (
        " Task: propose test scenarios only (they are validated elsewhere). Every "
        "`input_args` key must be a real parameter name. Use `confidence` LOW and "
        "`classification` HYPOTHESIS."
    ),
    "root_cause_analysis": (
        " Task: investigate one test failure. If no evidence-backed pattern matches, "
        "return an empty `hypotheses` list and `confidence` UNKNOWN. `historical_incidents` "
        "are context only and must not change your confidence."
    ),
    "patch_proposal": (
        " Task: propose one minimal fix. `old_snippet` must be an exact substring of the "
        "supplied source. If no recognised pattern applies, set `strategy` to \"none\", "
        "leave the snippets empty, and use `confidence` UNKNOWN."
    ),
    "modernization_recommendation": (
        " Task: map each target to one of add_tests / extract_dependency / refactor / "
        "replace_dependency / rewrite. Never prefer `rewrite` unless the target is "
        "CRITICAL legacy risk and nothing cheaper applies. Do not order the items."
    ),
}

_USER_TEMPLATE = (
    "Context (deterministic engine output):\n{payload}\n\n"
    "known_refs (the only refs you may cite):\n{known_refs}\n\n"
    "Call the tool now."
)


def _missing_sdk() -> ArchonError:
    return ArchonError(
        ErrorCode.AI_PROVIDER_ERROR,
        "the 'anthropic' package is not installed",
        recoverability=Recoverability.NON_RECOVERABLE,
        suggested_action="Install it with: pip install -e 'backend[claude]'",
    )


def _strip_titles(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


class ClaudeAIProvider(AIProvider):
    name = "claude"

    def __init__(self, *, settings: Settings | None = None, client: Any | None = None) -> None:
        if anthropic is None and client is None:
            raise _missing_sdk()
        s = settings or get_settings()
        self._model: str = s.ai_model
        self._timeout: float = s.ai_timeout_seconds
        self._max_retries: int = max(0, s.ai_max_retries)
        self._max_output_tokens: int = s.ai_max_output_tokens
        self._max_context_chars: int = s.ai_max_context_chars
        self._last_usage: tuple[int | None, int | None] = (None, None)
        self._last_latency_ms: int = 0
        if client is not None:
            self._client = client
        else:  # pragma: no cover - needs a real key
            self._client = anthropic.Anthropic(api_key=s.anthropic_api_key)

    # --- AIProvider contract -------------------------------------------------

    def _generate(self, operation: str, schema: type[BaseModel], context: dict) -> dict:
        system, user = self._render_prompt(operation, context)
        tool = {
            "name": f"emit_{operation}",
            "description": f"Return the {operation} result as structured data.",
            "input_schema": self._tool_input_schema(schema),
        }

        started = time.monotonic()
        resp = self._with_retries(
            operation,
            lambda: self._client.messages.create(
                model=self._model,
                max_tokens=self._max_output_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                timeout=self._timeout,
            ),
        )
        self._last_latency_ms = int((time.monotonic() - started) * 1000)
        usage = getattr(resp, "usage", None)
        self._last_usage = (
            getattr(usage, "input_tokens", None),
            getattr(usage, "output_tokens", None),
        )

        block = next(
            (b for b in getattr(resp, "content", []) if getattr(b, "type", None) == "tool_use"),
            None,
        )
        if block is None:
            raise AIOutputError(
                "Claude did not call the structured-output tool", operation=operation
            )
        return dict(block.input)

    # --- prompt rendering --------------------------------------------------

    def _render_prompt(self, operation: str, context: dict) -> tuple[str, str]:
        builder = getattr(self, f"_ctx_{operation}", None)
        if builder is None:
            raise AIOutputError(
                f"ClaudeAIProvider has no prompt template for {operation!r}", operation=operation
            )
        payload = self._clip_context(builder(context))
        known = {
            k: sorted(v)[:200]
            for k, v in (context.get("known_refs") or {}).items()
        }
        system = _SYSTEM_BASE + _OP_RULES.get(operation, "")
        user = _USER_TEMPLATE.format(
            payload=json.dumps(payload, indent=2, default=str),
            known_refs=json.dumps(known, indent=2, default=str),
        )
        return system, user

    @staticmethod
    def _ctx_historical_intent(ctx: dict) -> dict:
        return {
            "component": ctx.get("component", {}),
            "callers": ctx.get("callers", []),
            "callees": ctx.get("callees", []),
            "tests": ctx.get("tests", []),
            "commit_refs": ctx.get("commit_refs", []),
        }

    @staticmethod
    def _ctx_behavior_analysis(ctx: dict) -> dict:
        return {
            "component": ctx.get("component", {}),
            "inputs": ctx.get("inputs", []),
            "outputs": ctx.get("outputs", []),
            "side_effects": ctx.get("side_effects", []),
            "likely_invariants": ctx.get("likely_invariants", []),
        }

    @staticmethod
    def _ctx_assumption_analysis(ctx: dict) -> dict:
        return {
            "assumption": ctx.get("assumption", {}),
            "component": ctx.get("component", {}),
            "tests": ctx.get("tests", []),
        }

    @staticmethod
    def _ctx_test_generation(ctx: dict) -> dict:
        return {
            "component": ctx.get("component", {}),
            "has_raise": bool(ctx.get("has_raise")),
            "has_dependencies": bool(ctx.get("has_dependencies")),
        }

    @staticmethod
    def _ctx_root_cause_analysis(ctx: dict) -> dict:
        return {
            "failure": ctx.get("failure", {}),
            "component": ctx.get("component"),
            "assumptions": ctx.get("assumptions", []),
            "historical_incidents": ctx.get("historical_incidents", []),
        }

    @staticmethod
    def _ctx_patch_proposal(ctx: dict) -> dict:
        return {
            "component": ctx.get("component", {}),
            "divisor_param": ctx.get("divisor_param"),
            "return_expr_source": ctx.get("return_expr_source"),
            "indent": ctx.get("indent", ""),
            "strategy_hint": ctx.get("strategy_hint"),
        }

    @staticmethod
    def _ctx_modernization_recommendation(ctx: dict) -> dict:
        return {"targets": ctx.get("targets", [])}

    # --- structured-output schema ---------------------------------------

    @staticmethod
    def _tool_input_schema(schema: type[BaseModel]) -> dict:
        raw = _strip_titles(schema.model_json_schema())
        raw["type"] = "object"
        raw["additionalProperties"] = False
        return raw

    # --- token budget --------------------------------------------------

    def _clip_context(self, payload: dict) -> dict:
        budget = self._max_context_chars
        if len(json.dumps(payload, default=str)) <= budget:
            return payload
        payload = json.loads(json.dumps(payload, default=str))  # deep copy, JSON-safe
        sentinel = "…(truncated for token budget)"
        for _ in range(40):
            if len(json.dumps(payload)) <= budget:
                break
            target_key, target_len = None, 1
            for key in _LIST_CLIP_PRIORITY:
                val = payload.get(key)
                if isinstance(val, list) and len(val) > target_len:
                    target_key, target_len = key, len(val)
            if target_key is None:
                break
            keep = max(1, target_len // 2)
            payload[target_key] = payload[target_key][:keep] + [sentinel]
        # last resort: hard-cap any remaining oversize string field
        if len(json.dumps(payload)) > budget:
            cap = max(200, budget // 4)
            for key, val in list(payload.items()):
                if isinstance(val, str) and len(val) > cap:
                    payload[key] = val[:cap] + sentinel
        return payload

    # --- retry / error mapping --------------------------------------

    def _with_retries(self, operation: str, call):
        exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return call()
            except Exception as e:  # noqa: BLE001 - classified immediately below
                exc = e
                kind = self._classify(e)
                if kind == "output":
                    raise AIOutputError(
                        f"Claude rejected the request for {operation!r}",
                        operation=operation, detail=str(e),
                    ) from e
                if kind == "config":
                    raise AIProviderError(
                        f"Claude call for {operation!r} failed (check the API key / model)",
                        operation=operation, detail=str(e),
                    ) from e
                # transient
                if attempt >= self._max_retries:
                    break
                delay = min(2 ** attempt, 8) + random.random()
                log.warning(
                    "claude call transient failure - retrying",
                    extra={"extra_fields": {"operation": operation, "attempt": attempt + 1}},
                )
                time.sleep(delay)
        raise AIProviderError(
            f"Claude call for {operation!r} failed after {self._max_retries + 1} attempt(s)",
            operation=operation, detail=str(exc),
        ) from exc

    @staticmethod
    def _classify(e: Exception) -> str:
        """-> 'transient' | 'config' | 'output'."""
        if anthropic is not None:
            if isinstance(e, (anthropic.APITimeoutError, anthropic.APIConnectionError)):
                return "transient"
            if isinstance(e, anthropic.RateLimitError):
                return "transient"
            if isinstance(e, anthropic.BadRequestError):
                return "output"
            if isinstance(e, anthropic.APIStatusError):
                status = getattr(e, "status_code", None)
                if status in _RETRY_STATUS:
                    return "transient"
                if status in (400, 422):
                    return "output"
                return "config"
        status = getattr(e, "status_code", None)
        if status in _RETRY_STATUS:
            return "transient"
        if status in (400, 422):
            return "output"
        if status in (401, 403, 404):
            return "config"
        return "transient"
