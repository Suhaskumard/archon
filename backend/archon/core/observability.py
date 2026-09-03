"""Observability: Prometheus metrics + lightweight structured tracing (spec section 55).

* ``metrics`` - a dedicated ``CollectorRegistry`` with the run / stage / queue / sandbox /
  AI series the ops screen and ``/metrics`` expose. Kept off the global default registry so
  tests can ``reset_metrics()`` between cases and a re-import never double-registers.
* ``span(name, **fields)`` - a context manager that logs a structured ``trace`` record with
  a millisecond duration and (optionally) feeds a stage-duration histogram. This is
  "traces via structured logging" - an OpenTelemetry exporter can be layered on later
  without touching call sites.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from archon.core.logging import get_logger

_trace_log = get_logger("archon.trace")
_audit_log = get_logger("archon.audit")


def audit(event: str, **fields: Any) -> None:
    """Structured audit record for a run/job state transition (spec section 55)."""
    _audit_log.info(event, extra={"extra_fields": {"audit": event, **fields}})

_STAGE_BUCKETS = (0.05, 0.25, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)
_AI_BUCKETS = (0.25, 0.5, 1, 2, 4, 8, 15, 30, 60)


@dataclass
class _Metrics:
    registry: CollectorRegistry
    stage_duration: Histogram
    run_outcomes: Counter
    runs_active: Gauge
    jobs_queued: Gauge
    jobs_running: Gauge
    sandbox_containers: Gauge
    ai_calls: Counter
    ai_latency: Histogram
    ai_tokens: Counter
    http_requests: Counter


def _build() -> _Metrics:
    reg = CollectorRegistry()
    return _Metrics(
        registry=reg,
        stage_duration=Histogram(
            "archon_stage_duration_seconds", "Pipeline stage wall-clock duration",
            ["stage", "mode", "outcome"], registry=reg, buckets=_STAGE_BUCKETS,
        ),
        run_outcomes=Counter(
            "archon_run_outcomes_total", "Completed analysis runs by terminal state",
            ["outcome", "mode"], registry=reg,
        ),
        runs_active=Gauge(
            "archon_runs_active", "Runs currently RUNNING", registry=reg,
        ),
        jobs_queued=Gauge(
            "archon_jobs_queued", "Jobs in QUEUED state", registry=reg,
        ),
        jobs_running=Gauge(
            "archon_jobs_running", "Jobs in RUNNING state", registry=reg,
        ),
        sandbox_containers=Gauge(
            "archon_sandbox_containers", "Live archon-managed sandbox containers", registry=reg,
        ),
        ai_calls=Counter(
            "archon_ai_calls_total", "AI provider calls",
            ["provider", "operation", "outcome"], registry=reg,
        ),
        ai_latency=Histogram(
            "archon_ai_call_latency_seconds", "AI provider call latency",
            ["provider", "operation"], registry=reg, buckets=_AI_BUCKETS,
        ),
        ai_tokens=Counter(
            "archon_ai_tokens_total", "AI provider tokens (cost proxy)",
            ["provider", "direction"], registry=reg,
        ),
        http_requests=Counter(
            "archon_http_requests_total", "HTTP requests handled",
            ["method", "route", "status"], registry=reg,
        ),
    )


metrics: _Metrics = _build()


def reset_metrics() -> None:
    """Test hook - drop every series and rebuild the registry."""
    global metrics
    metrics = _build()


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(metrics.registry), CONTENT_TYPE_LATEST


@dataclass
class Span:
    name: str
    fields: dict[str, Any] = field(default_factory=dict)

    def set(self, **kw: Any) -> None:
        self.fields.update(kw)


@contextmanager
def span(name: str, **fields: Any):
    """Structured trace span. Logs ``trace`` with ``duration_ms`` + ``ok`` on exit."""
    sp = Span(name=name, fields=dict(fields))
    started = time.monotonic()
    ok = True
    try:
        yield sp
    except BaseException:
        ok = False
        raise
    finally:
        dur_ms = round((time.monotonic() - started) * 1000, 2)
        _trace_log.info(
            "trace",
            extra={"extra_fields": {"span": name, "duration_ms": dur_ms, "ok": ok, **sp.fields}},
        )


def observe_stage(stage: str, mode: str, seconds: float, *, outcome: str = "ok") -> None:
    metrics.stage_duration.labels(stage=stage, mode=mode, outcome=outcome).observe(seconds)


def record_run_outcome(outcome: str, mode: str) -> None:
    metrics.run_outcomes.labels(outcome=outcome, mode=mode).inc()


def record_ai_call(
    provider: str, operation: str, *, outcome: str, latency_s: float | None = None,
    input_tokens: int | None = None, output_tokens: int | None = None,
) -> None:
    metrics.ai_calls.labels(provider=provider, operation=operation, outcome=outcome).inc()
    if latency_s is not None:
        metrics.ai_latency.labels(provider=provider, operation=operation).observe(latency_s)
    if input_tokens:
        metrics.ai_tokens.labels(provider=provider, direction="input").inc(input_tokens)
    if output_tokens:
        metrics.ai_tokens.labels(provider=provider, direction="output").inc(output_tokens)
