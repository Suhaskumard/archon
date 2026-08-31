"""Deterministic, offline AI provider (spec section 18 - mock provider first).

Every response is a pure function of the supplied context - no network, no randomness,
same input -> same output. It never invents repository facts: it only rephrases and
classifies what the deterministic engines already found, and cites the component/commit
refs the caller passed in.
"""

from __future__ import annotations

from pydantic import BaseModel

from archon.providers.ai.base import AIProvider

_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_UNRANK = {0: "LOW", 1: "MEDIUM", 2: "HIGH"}
_BASE_RISK = {
    "division": "MEDIUM", "dict_key": "MEDIUM", "null": "MEDIUM", "global_state": "MEDIUM",
    "empty_collection": "MEDIUM", "external_api": "MEDIUM",
    "environment": "LOW", "timezone": "LOW", "ordering": "LOW", "initialization": "MEDIUM",
    "schema": "LOW",
}

_SUGGESTED_TEST = {
    "null": "Call with the argument set to None and assert the intended behaviour (no AttributeError).",
    "division": "Call with a zero divisor and assert it does not raise ZeroDivisionError.",
    "empty_collection": "Call with an empty collection and assert it does not raise IndexError/StopIteration.",
    "dict_key": "Call with a key that is absent from the mapping and assert the intended behaviour.",
    "global_state": "Reset the module-level global between tests and assert calls are isolated.",
    "initialization": "Invoke before any initialiser runs and assert a clear error, not a crash.",
    "environment": "Unset the environment variable and assert a documented default or a clear error.",
    "external_api": "Simulate the external call failing and assert the failure is handled.",
    "timezone": "Run under two timezones (or a frozen clock) and assert identical results.",
    "ordering": "Feed inputs in a different order and assert the output is unchanged.",
    "schema": "Pass input missing the expected key/field and assert a validation error, not a KeyError.",
}


def _first_line(text: str | None) -> str:
    return (text or "").strip().splitlines()[0].strip() if text else ""


def _phrase(seq: list[str], empty: str) -> str:
    seq = [s for s in seq if s]
    if not seq:
        return empty
    if len(seq) == 1:
        return seq[0]
    return ", ".join(seq[:-1]) + f" and {seq[-1]}"


class MockAIProvider(AIProvider):
    name = "mock"

    def _generate(self, operation: str, schema: type[BaseModel], context: dict) -> dict:
        handler = getattr(self, f"_op_{operation}", None)
        if handler is None:  # pragma: no cover - guards future operations
            raise NotImplementedError(f"MockAIProvider has no handler for {operation!r}")
        return handler(context)

    # --- operations -----------------------------------------------------------

    def _op_historical_intent(self, ctx: dict) -> dict:
        comp = ctx.get("component", {})
        qn = comp.get("qualified_name", "?")
        name = comp.get("name", qn.split(".")[-1])
        git = comp.get("git", {}) or {}
        callers = ctx.get("callers", [])
        tests = ctx.get("tests", [])
        doc = _first_line(comp.get("docstring"))

        purpose = doc or f"Implements {name.replace('_', ' ')} for the {comp.get('role', 'codebase')}."
        commit_count = git.get("commit_count")
        age = git.get("age_days")
        ctx_bits = []
        if age is not None:
            ctx_bits.append(f"first seen ~{age} day(s) ago")
        if commit_count is not None:
            ctx_bits.append(f"touched by {commit_count} commit(s)")
        authors = git.get("distinct_authors")
        if authors:
            ctx_bits.append(f"{authors} distinct author(s)")
        historical_context = "; ".join(ctx_bits) or "no git history available"

        role_line = f"A {comp.get('role', 'module')} component"
        if callers:
            role_line += f" used by {_phrase(callers[:4], '')}"
        current_role = role_line + "."

        evidence = [{"kind": "component", "ref": qn, "detail": "subject of the analysis"}]
        for sha in ctx.get("commit_refs", [])[:3]:
            evidence.append({"kind": "commit", "ref": sha, "detail": "touched this component"})

        has_signal = bool(doc) or commit_count
        return {
            "likely_purpose": purpose,
            "historical_context": historical_context,
            "current_role": current_role,
            "evidence": evidence,
            "confidence": "MEDIUM" if has_signal else "LOW",
            "classification": "INFERENCE" if doc else "HYPOTHESIS",
            "reasoning_summary": (
                "Derived from the component name/docstring and its git history; "
                "no runtime behaviour was executed."
            ),
            "recommended_action": None if tests else "Add characterization tests before changing this.",
        }

    def _op_behavior_analysis(self, ctx: dict) -> dict:
        comp = ctx.get("component", {})
        qn = comp.get("qualified_name", "?")
        name = comp.get("name", qn.split(".")[-1])
        inputs = ctx.get("inputs", [])
        outputs = ctx.get("outputs", [])
        side_effects = ctx.get("side_effects", [])
        invariants = ctx.get("likely_invariants", [])

        summary = (
            f"{name} accepts {_phrase(inputs, 'no explicit inputs')} and "
            f"produces {_phrase(outputs, 'no explicit return value')}"
        )
        if side_effects:
            summary += f"; it also {_phrase(side_effects, '')}"
        summary += "."

        return {
            "summary": summary,
            "inputs": inputs,
            "outputs": outputs,
            "side_effects": side_effects,
            "likely_invariants": invariants,
            "evidence": [{"kind": "component", "ref": qn, "detail": "static analysis subject"}],
            "confidence": "MEDIUM",
            "classification": "INFERENCE",
            "reasoning_summary": "Assembled from the AST signature, raised exceptions and call edges.",
        }

    def _op_test_generation(self, ctx: dict) -> dict:
        comp = ctx.get("component", {})
        qn = comp.get("qualified_name", "?")
        cid = comp.get("id", "")
        params: list[str] = comp.get("params", [])
        has_raise = bool(ctx.get("has_raise"))
        has_dependencies = bool(ctx.get("has_dependencies"))

        def args(value) -> dict:
            return {p: value for p in params}

        scenarios = [
            {
                "kind": "UNIT",
                "description": f"Call {qn} with plain default-shaped arguments.",
                "input_args": args(0),
                "expected_behavior": "returns",
            },
            {
                "kind": "BOUNDARY",
                "description": f"Call {qn} with boundary values (0, -1) for each argument.",
                "input_args": args(-1),
                "expected_behavior": "returns",
            },
            {
                "kind": "INVALID_INPUT",
                "description": f"Call {qn} with None for each argument.",
                "input_args": args(None),
                "expected_behavior": "raises",
            },
        ]
        if has_raise:
            scenarios.append({
                "kind": "EXCEPTION",
                "description": f"{qn} contains a raise statement; exercise the error path.",
                "input_args": args(None),
                "expected_behavior": "raises",
            })
        scenarios.append({
            "kind": "REGRESSION",
            "description": (
                f"Placeholder regression scenario for {qn} - no historical failure data "
                "exists yet (lands in a later phase); this pins today's default-argument behaviour."
            ),
            "input_args": args(0),
            "expected_behavior": "returns",
        })
        if has_dependencies:
            scenarios.append({
                "kind": "INTEGRATION",
                "description": f"{qn} calls other components; exercise it end-to-end.",
                "input_args": args(0),
                "expected_behavior": "returns",
            })

        return {
            "target_component": cid,
            "scenarios": scenarios,
            "evidence": [{"kind": "component", "ref": qn, "detail": "test-generation subject"}],
            "confidence": "LOW",
            "classification": "HYPOTHESIS",
            "reasoning_summary": (
                "Template-generated from the component's signature and simple source scans "
                "(raise statements, outgoing call edges) - no real type inference."
            ),
            "recommended_action": "Review each generated test before trusting it as a real spec.",
        }

    def _op_assumption_analysis(self, ctx: dict) -> dict:
        a = ctx.get("assumption", {})
        comp = ctx.get("component", {})
        qn = comp.get("qualified_name", "?")
        git = comp.get("git", {}) or {}
        tests = ctx.get("tests", [])
        kind = a.get("kind", "unknown")

        base = _RANK[_BASE_RISK.get(kind, "LOW")]
        bump = 0
        if (git.get("commit_count") or 0) >= 2:
            bump += 1
        if not tests:
            bump += 1
        risk = _UNRANK[min(base + bump, 2)]

        evidence = [{"kind": "component", "ref": qn, "detail": a.get("location", "")}]
        if comp.get("path"):
            evidence.append({"kind": "file", "ref": comp["path"], "detail": a.get("location", "")})

        return {
            "kind": kind,
            "description": a.get("description", f"Hidden {kind} assumption."),
            "risk": risk,
            "suggested_test": _SUGGESTED_TEST.get(kind, "Add a targeted test that violates the assumption."),
            "evidence": evidence,
            "confidence": "MEDIUM",
            "classification": "HYPOTHESIS",
            "reasoning_summary": (
                f"Pattern-matched a {kind} assumption in source; risk weighted by churn "
                f"({git.get('commit_count', 0)} commits) and test coverage."
            ),
            "recommended_action": "Add the suggested test, then decide whether the assumption is safe.",
        }
