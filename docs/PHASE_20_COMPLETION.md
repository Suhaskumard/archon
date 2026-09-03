# Phase 20 — Observability, scale & operability — Completion Record

Per `docs/ROADMAP.md` Phase 20, the production-readiness capstone. Adds Prometheus metrics
+ a structured trace/audit layer, an ops run view, hardened deployment, a real
multi-language contract, per-client abuse controls, and a `pytest -m perf` tier. No spec
loop behaviour changes — this is all instrumentation, enforcement, and packaging.

## Scope delivered

| Area | Detail |
|---|---|
| **Metrics** | `core/observability.py` — a dedicated `CollectorRegistry` (off the global default so tests `reset_metrics()`). `GET /metrics` (`api/routers/admin.py`) renders: `archon_stage_duration_seconds{stage,mode,outcome}` (Histogram, from the orchestrator's per-stage `monotonic()` delta), `archon_run_outcomes_total{outcome,mode}`, `archon_runs_active` / `archon_jobs_queued` / `archon_jobs_running` (Gauges refreshed from the DB on scrape), `archon_ai_calls_total{provider,operation,outcome}` + `archon_ai_call_latency_seconds` + `archon_ai_tokens_total{provider,direction}` (from `AIProvider.complete_structured`, non-mock only — a cost proxy), `archon_sandbox_containers`, `archon_http_requests_total{method,route,status}` (app middleware; `/metrics` itself excluded). `prometheus-client` is now a core dependency (~60 KB, no transitive deps). |
| **Tracing / audit** | `span(name, **fields)` — a context manager that logs one `archon.trace` record with `duration_ms` + `ok`. `audit(event, **fields)` — an `archon.audit` record for **every** run/job state transition: `run.queued` (JobManager), `run.claimed` / `run.completed` / `run.failed` / `run.cancelled` / `run.requeued` (worker + `requeue_stale`), `stage.enter` (orchestrator), `worker.draining` (SIGTERM). This is the "structured audit log of every state transition" §55 asks for — no new table. An OTel exporter can wrap `span()` later without touching call sites. |
| **Ops view** | `GET /admin/runs` — one row per run: repo URL, commit, mode, state, current/last stage, trigger, start/end, wall-clock `duration_seconds`, progress, `error`, `ai_evidence_count` (Evidence rows whose `produced_by` starts `claude:`). `state` filter, `limit`/`offset`. Frontend `#/ops` route (`OpsRoute.tsx`) — filterable table + links to `/metrics` and `/readyz`, and a header nav (`Repositories · Operations`). |
| **Readiness** | `GET /readyz` — DB reachable **AND** `migrate.current_revision() == head_revision()` → 503 otherwise (`archon db-upgrade` fixes it). `/healthz` stays liveness. New `migrate.head_revision()` / `current_revision()` / `is_up_to_date()`. |
| **Deployment** | `docker/docker-compose.prod.yml` (new) — non-root, per-service `HEALTHCHECK`, `deploy.resources.limits`, `restart: unless-stopped`, `stop_grace_period: 120s`, worker `replicas`, secrets via `--env-file ../.env.prod` (`.env.prod.example` added). `Dockerfile.api` / `Dockerfile.worker` hardened: `useradd archon` (uid 10001), `USER archon`, `HEALTHCHECK`, `chown /data`. `migrate.upgrade()` takes a Postgres session advisory lock (`pg_advisory_lock`, no-op on SQLite) so N replicas can all run `db-upgrade` on start and only one migrates. `db/base.get_engine` gains `pool_pre_ping` (always) + `pool_size`/`max_overflow` (non-sqlite). |
| **Multi-language (§16-17)** | `assess_support` returns `language_breakdown` (ext → count, `_LANG_BY_EXT` covers 20 languages) + `non_python_file_count` / `non_python_languages` helpers. The `SNAPSHOTTING` stage emits a `NON_PYTHON_SUMMARY` `FACT` Evidence row (counts + languages, `refs.language_breakdown`) for a `PARTIALLY_SUPPORTED` repo with non-Python code, and a shallow-history `INFERENCE` row when `commit_count <= 1`. The Python slice is still fully analysed. |
| **Run deadline** | The orchestrator checks `time.monotonic() > deadline` (`limits.max_analysis_duration_seconds`) before each stage → structured `TIMEOUT` `ArchonError` with `context.limit_seconds` + `stopped_before_stage`. |
| **Abuse controls** | `core/ratelimit.RateLimiter` — in-process per-client fixed-window limiter (single-node; a shared limiter is the documented next step). `rate_limit_runs` (30/min) on `POST /repositories/{id}/runs`, `rate_limit_webhook` (120/min) on `POST /webhooks/github`, keyed on `X-Forwarded-For` / `request.client.host` → **429** `RATE_LIMITED`. App middleware rejects a body over `max_request_bytes` (2 MiB) → **413** `REQUEST_TOO_LARGE` before it is read. New `ErrorCode.RATE_LIMITED` (429) / `REQUEST_TOO_LARGE` (413). |
| **Settings** | `db_pool_size` / `db_max_overflow` / `db_pool_pre_ping`, `max_request_bytes`, `rate_limit_runs_per_minute` / `rate_limit_webhook_per_minute` / `rate_limit_enabled`, `metrics_enabled`. `.env.example` + `.env.prod.example` updated. |
| **Perf tier** | `tests/perf/` + a `perf` pytest marker deselected by default (`addopts = "-q -m 'not perf'"`); `make perf` runs it. `test_caching_and_reuse.py` — a 2nd run over the same commit shares the immutable snapshot and does not duplicate `Component`/`Dependency` rows; a 3rd run's counts are identical; a new commit gets a fresh snapshot. `test_concurrency_and_limits.py` — `max_concurrent_runs` claim cap; `max_file_count` truncation + reason; pre-clone size guard; **Postgres `SELECT … FOR UPDATE SKIP LOCKED`** contention (gated on `ARCHON_TEST_POSTGRES_URL`); container **reaper** (gated on `ARCHON_RUN_REAPER_TEST` + Docker). |

## Verification

| Check | Result |
|---|---|
| `pytest -q` (no Docker, no key; perf deselected) | green — new observability / ratelimit / multilang / admin-api / phase20-acceptance tests pass; Docker + gated-Claude tests skip |
| `pytest -m perf` | 5 pass, 2 skip (Postgres + reaper, correctly gated) |
| `GET /metrics` via TestClient | 200, `text/plain`, contains every declared series; `/metrics` itself not counted in `http_requests_total` |
| `GET /readyz` on a migrated DB | 200 `{"status":"ready","revision":"0013_webhooks"}` |
| `GET /admin/runs` after a run | reports state / mode / repo / `duration_seconds` / `trigger`; `?state=` filters |
| rate limit | `ARCHON_RATE_LIMIT_RUNS_PER_MINUTE=2` → 3rd `POST .../runs` in the window → 429 `RATE_LIMITED` |
| request cap | `ARCHON_MAX_REQUEST_BYTES=200` → oversized POST → 413 `REQUEST_TOO_LARGE` |
| multi-language | polyglot fixture → `support_level == PARTIALLY_SUPPORTED`, exactly one `NON_PYTHON_SUMMARY` Evidence row naming JavaScript/Go, Python components still extracted |
| crash recovery | job forced to RUNNING with a stale heartbeat → a fresh worker's `requeue_stale` rescues it → run reaches `COMPLETED` |
| run deadline | `max_analysis_duration_seconds=0` → run fails with structured `TIMEOUT` (`context.limit_seconds == 0`) |
| `ruff check archon tests alembic` | clean |
| frontend `typecheck` / `test:cov` (95 tests, +3 OpsRoute) / `build` | green — coverage 98.3 % lines / 78.4 % branch (gate 80/75) |
| `migrate.upgrade` advisory lock | no-op path exercised on SQLite; the pg path is a `pg_advisory_lock`/`pg_advisory_unlock` pair around `command.upgrade` |

## Known limitations / deferred

* **Traces are structured logs, not OTel spans.** `span()` emits an `archon.trace` record;
  wiring an OpenTelemetry exporter (OTLP) is a config-only follow-up that does not touch
  call sites. Prometheus `/metrics` is the load-bearing observability surface and is real.
* **Rate limiting is per-process.** Each API replica keeps its own window map; a shared
  limiter (Redis / ingress) is needed for a true multi-replica limit. The single-node
  compose stack and every test are covered.
* **`docker compose -f docker-compose.prod.yml up` is not executed here** — no Docker
  daemon in this environment (same gate as every Phase 7+ sandbox test). The compose file
  and Dockerfiles are shipped and reviewed; `docker compose config` validates syntax.
* **Crash recovery restarts the run from `plan[0]`**, not a mid-run checkpoint — the
  orchestrator docstring has always said "recovery is by requeue". True
  resume-from-checkpoint (reconstruct the clone workspace from `snapshot.workspace_ref`)
  remains a larger piece of work; the acceptance bar ("kill the worker mid-run and
  restarting resumes to COMPLETED") is met by the stale-heartbeat requeue path.
* **Postgres SKIP LOCKED + container-reaper perf tests are gated**, not run in CI (need a
  live Postgres / Docker). The claim-cap, caching, and limit tests run unconditionally
  under `make perf`.
