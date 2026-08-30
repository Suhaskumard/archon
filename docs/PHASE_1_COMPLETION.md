# Phase 1 — Foundation & Repository Ingestion — Completion Record

Per spec §62 step 11 ("Record what was completed") and the plan's per-phase completion
gate.

## Scope delivered

The ingestion prefix of the ARCHON pipeline, end to end, for **local** and **GitHub**
repositories:

```
POST /repositories ─▶ POST /repositories/{id}/runs ─▶ Job(QUEUED)
   ─▶ worker claims ─▶ INGESTING (validate · metadata · secure clone)
   ─▶ SNAPSHOTTING (support classification · immutable RepositorySnapshot)
   ─▶ run COMPLETED, evidence written
```

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Configuration | `archon/config.py` | `Settings` + `RepositoryLimits`, all `ARCHON_*` env-overridable |
| Logging | `archon/core/logging.py` | structured; redacts URL creds, `gh*_` tokens, secret-ish keys |
| Error taxonomy | `archon/core/errors.py` | `ArchonError` = code + message + context + recoverability + suggested action + HTTP status (§54) |
| IDs / versions | `archon/core/ids.py`, `archon/core/versions.py` | ULID ids; engine-version registry pinned onto each run |
| Database | `archon/db/` + `alembic/` | 6 tables, `0001_initial`, SQLite + PostgreSQL, programmatic `migrate.upgrade()` |
| State machine | `archon/jobs/state_machine.py` | explicit `RUN_TRANSITIONS`, forward-only `STAGE_ORDER`, illegal moves raise |
| Job queue | `archon/jobs/manager.py` | DB-backed, `FOR UPDATE SKIP LOCKED` on PG, dedupe + idempotency + stale-requeue + cooperative cancel |
| Worker | `archon/jobs/worker.py` | poll loop; transient failures retried, others → FAILED; cancellations recorded |
| Workspaces | `archon/workspace/manager.py` | disposable, quota-checked, path-traversal-safe, orphan reaper |
| Repo providers | `archon/providers/repo/` | ABC + Local + GitHub; URL/shorthand parsing, GitHub REST metadata w/ retry + error mapping, secure `git` clone, ref checkout, size gate |
| Support classifier | `archon/pipeline/support.py` | SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED + machine-readable reasons (§17) |
| Orchestrator | `archon/pipeline/orchestrator.py` | walks stages, per-stage idempotency, emits classified `Evidence`, persists checkpoint |
| REST API | `archon/api/` | repositories + runs + evidence + cancel; pagination; OpenAPI; structured error bodies |
| CLI | `archon/cli/main.py` | `db-upgrade`, `serve`, `worker`, `analyze <url|path> --wait` |
| Frontend | `frontend/` | Vite + React + TS; Repository Management screen + live-polling Run view; data only from the real API |
| Deployment | `docker/`, `Makefile`, `.env.example` | `docker compose` = api + worker + postgres |

## Tests — `cd backend && pytest`

**63 passed** (unit + integration + acceptance). Coverage 83 % of `archon/`.

| Tier | Files | Covers |
|---|---|---|
| unit | ids, errors+redaction, state machine, workspace manager, github parse, github metadata (offline via `httpx.MockTransport`), support classifier | transition legality, path-traversal refusal, quota, secret scrubbing, URL variants, GitHub 404/401/403-private/403-ratelimited/429 mapping, 5xx retry |
| integration | pipeline (local), api, cli | worker ingests a real git repo; snapshot reuse for same commit; ref checkout; cancellation; full HTTP lifecycle; 409 dedupe; idempotency key; 404s; OpenAPI; `archon analyze` headless |
| acceptance | `test_phase1_ingestion.py` | evidence-backed immutable snapshot pinned to a 40-hex SHA; support contract + notes; engine-version pinning; structured errors for bad targets / non-git dirs; stage failure recorded (never swallowed) |

The acceptance fixture repo (`tests/fixtures/build_test_repo.py`) builds a **real** git
repo with 3 commits, multiple modules with import/call edges, a manifest, existing tests,
a **known test gap** (`inventory.reserve`) and a **reproducible bug** (`calculator.divide`
divide-by-zero) — the latter two are dormant until Phases 8–9.

## Verified manually

* `archon analyze ./legacy-shop --wait` → run `COMPLETED`, snapshot `SUPPORTED`, 2 FACT
  evidence rows.
* `archon serve` + `curl` POST repo → POST run → `archon worker` → `GET /runs/{id}` shows
  `COMPLETED`, snapshot with commit SHA + `support_notes`, evidence list. Re-running the
  same commit reused the existing `snapshot_id` (immutability + dedupe).
* `ruff check archon tests alembic` → clean.
* `alembic upgrade head` → clean on SQLite (PostgreSQL path is exercised by
  `docker/docker-compose.yml`; not run in this environment).

## Known limitations / deferred

* PostgreSQL only smoke-tested via compose config, not in CI here.
* Frontend is the two Phase 1 screens only; the full area list (§48) fills in per phase.
* Stages after `SNAPSHOTTING` are declared in `STAGE_ORDER` but not yet executed — Phase 2
  (source intelligence) is next per the plan's priority order.
