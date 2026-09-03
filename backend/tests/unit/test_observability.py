"""Prometheus metrics registry + structured trace/audit helpers (Phase 20, spec section 55)."""

from __future__ import annotations

from archon.core.observability import (
    metrics,
    observe_stage,
    record_ai_call,
    record_run_outcome,
    render_metrics,
    reset_metrics,
    span,
)


def test_metrics_render_is_prometheus_text():
    body, content_type = render_metrics()
    assert b"archon_stage_duration_seconds" in body
    assert b"archon_run_outcomes_total" in body
    assert "text/plain" in content_type


def test_stage_and_outcome_counters_move():
    reset_metrics()
    observe_stage("ANALYZING_SOURCE", "FULL", 0.4)
    record_run_outcome("completed", "FULL")
    record_run_outcome("completed", "FULL")
    body = render_metrics()[0].decode()
    assert 'archon_run_outcomes_total{mode="FULL",outcome="completed"} 2.0' in body
    assert 'archon_stage_duration_seconds_count{mode="FULL",outcome="ok",stage="ANALYZING_SOURCE"} 1.0' in body


def test_record_ai_call_feeds_calls_latency_and_tokens():
    reset_metrics()
    record_ai_call("claude", "root_cause_analysis", outcome="ok", latency_s=2.5,
                   input_tokens=100, output_tokens=40)
    record_ai_call("claude", "root_cause_analysis", outcome="error")
    body = render_metrics()[0].decode()
    assert 'archon_ai_calls_total{operation="root_cause_analysis",outcome="ok",provider="claude"} 1.0' in body
    assert 'archon_ai_calls_total{operation="root_cause_analysis",outcome="error",provider="claude"} 1.0' in body
    assert 'archon_ai_tokens_total{direction="input",provider="claude"} 100.0' in body
    assert 'archon_ai_tokens_total{direction="output",provider="claude"} 40.0' in body


def test_reset_metrics_clears_series():
    record_run_outcome("failed", "FULL")
    reset_metrics()
    assert b"outcome=" not in render_metrics()[0]  # no label samples yet


def test_span_logs_a_trace_record(caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="archon.trace"):
        with span("unit-test-span", foo="bar") as sp:
            sp.set(rows=3)
    rec = next(r for r in caplog.records if r.name == "archon.trace")
    fields = rec.extra_fields
    assert fields["span"] == "unit-test-span"
    assert fields["ok"] is True
    assert fields["rows"] == 3
    assert "duration_ms" in fields


def test_span_marks_failure_but_reraises(caplog):
    import logging

    import pytest

    with caplog.at_level(logging.INFO, logger="archon.trace"):
        with pytest.raises(ValueError):
            with span("boom"):
                raise ValueError("x")
    rec = next(r for r in caplog.records if r.name == "archon.trace")
    assert rec.extra_fields["ok"] is False


def test_registry_is_isolated_from_the_global_default():
    # our series live only on our own CollectorRegistry
    import prometheus_client

    assert metrics.registry is not prometheus_client.REGISTRY
