# ARCHON Architecture (living document)

This records the architectural decisions that are **implemented** as of Phase 1, plus the
contracts later phases must honour. It is the source of truth the spec demands (§8, §9,
§60). Sections marked _(declared)_ are fixed decisions whose code lands in a later phase.

---

## 1. System shape

```
             ┌─────────────┐      ┌──────────────┐
   HTTP ───▶ │  FastAPI    │─────▶│  PostgreSQL  │◀────┐
             │  (archon.api)│      │  / SQLite    │     │
             └─────────────┘      └──────────────┘     │
                    │  creates AnalysisRun + Job (QUEUED)│
                    ▼                                    │
             ┌───────────────┐   claims job   ┌──────────┴────────┐
             │ jobs.worker   │───────────────▶│ pipeline.orchestr. │
             │ (poll loop)   │                │  walks STAGE_ORDER  │
             └───────────────┘                └─────────┬──────────┘
                                                        ▼
                                   providers.repo  +  workspace.WorkspaceManager
                                   (validate · metadata · secure clone · classify)
```

* **Deterministic-first (§2):** ingestion, cloning, git facts and support classification
  are all deterministic. No AI is involved in Phase 1; the `AIProvider` abstraction and a
  mock provider arrive in Phase 4.
* **Evidence-driven (§4):** every conclusion the pipeline reaches is written to the
  `evidence` table with a `Classification` (`FACT` / `INFERENCE` / `HYPOTHESIS` /
  `RECOMMENDATION`), a `produced_by` engine tag, and optional `confidence` + source
  location.
* **One integrated system:** the orchestrator is the single path. The API, the CLI
  (`archon analyze`) and the future bulk-Excel importer all enqueue the *same* `Job`.

### Package map (`backend/archon/`)

| Package | Responsibility |
|---|---|
| `config` | All tunables (env-overridable). `Settings`, `RepositoryLimits`. |
| `core` | `ids` (ULID), `errors` (taxonomy), `logging` (structured + secret redaction), `versions` (engine-version registry). |
| `domain` | Enums / value objects: `Classification`, `RunState`, `JobState`, `Stage`, `SupportLevel`, `RunMode`, `ProviderKind`. |
| `db` | SQLAlchemy models, engine/session, `migrate` (programmatic Alembic). |
| `providers/repo` | `RepositoryProvider` ABC, `LocalRepositoryProvider`, `GitHubRepositoryProvider`, `gitcli` safe wrapper. |
| `workspace` | `WorkspaceManager` — disposable, quota-checked, path-traversal-safe checkout dirs. |
| `jobs` | `state_machine`, `manager` (DB queue), `worker` (loop). |
| `pipeline` | `orchestrator` (stage walker), `support` (spec §17 classifier). |
| `api` | FastAPI app, routers, structured error handlers, ORM→DTO serialisers. |
| `cli` | `archon` — `db-upgrade`, `serve`, `worker`, `analyze`. |

---

## 2. Database schema (§9)

Phase 1 migration `0001_initial` creates six tables. Portable types only
(`native_enum=False` → `VARCHAR` + `CHECK` on both SQLite and Postgres). Every
analysis-output row carries `run_id`; snapshots are immutable once written.

| Table | Purpose | Key columns |
|---|---|---|
| `repositories` | A tracked repo. | `provider`, `url` (unique together), `owner`, `name`, `default_branch` |
| `repository_snapshots` | Immutable pin at one commit. | `repository_id`, `commit_sha` (unique together), `branch`, `workspace_ref`, `size_bytes`, `file_count`, `commit_count`, `support_level`, `support_notes` |
| `analysis_runs` | One pipeline execution. | `snapshot_id`, `mode`, `state`, `current_stage`, `last_completed_stage`, `engine_versions`, `config_hash`, `progress_pct`, `error` |
| `analysis_artifacts` | Pointers to large/generated files (fs/object, not inline). | `run_id`, `kind`, `storage`, `ref`, `sha256`, `size_bytes` |
| `evidence` | Central conclusion record (§4). | `run_id`, `stage`, `classification`, `summary`, `detail`, `source_path/line`, `confidence`, `produced_by`, `refs` |
| `jobs` | Background unit of work. | `run_id` (unique), `state`, `priority`, `attempts`/`max_attempts`, `idempotency_key` (unique), `dedupe_key`, `heartbeat_at`, `cancel_requested`, `error` |

Later phases add `components`, `dependencies`, `commits`, `risk_assessments`,
`legacy_dna`, … as incremental migrations on this baseline.

---

## 3. Analysis state machine (§10)

**Run states** and their only legal transitions (`archon/jobs/state_machine.py`):

```
PENDING ─▶ QUEUED ─▶ RUNNING ─▶ COMPLETED
   │         │          │──────▶ FAILED
   └─────────┴──────────┴──────▶ CANCELLED
COMPLETED / FAILED / CANCELLED are terminal (no outgoing edges).
```

**Stage order** (`STAGE_ORDER`) is the full pipeline from §67
(`INGESTING → SNAPSHOTTING → ANALYZING_SOURCE → … → MODERNIZING`). Rules enforced by
`RunStateMachine`:

* stage moves are **forward-only** along `STAGE_ORDER`; a backwards or repeat move raises
  `IllegalTransition`;
* a stage can only be entered while the run is `RUNNING`;
* `last_completed_stage` is the persisted checkpoint — resumption re-enters at the next
  stage;
* **idempotency:** re-running a stage first deletes the rows it owns
  (`DELETE FROM evidence WHERE run_id = ? AND stage = ?`) then rewrites them.

Phase 1 executes the `INGESTING` and `SNAPSHOTTING` prefix and then completes the run in
`INGEST_ONLY` mode. Analysis stages will _degrade and continue_ on failure (recording a
warning `Evidence`); MVP-loop stages will _fail the run_. _(the degrade/fail split is
declared; only fail-the-run is exercised in Phase 1.)_

---

## 4. Job / concurrency model (§15)

* The HTTP request creates `AnalysisRun` (PENDING→QUEUED) + `Job` (QUEUED) and returns
  immediately with `202` + `Location: /runs/{id}`.
* A separate **worker** process (`archon worker`, or `Worker().tick()` inline for the CLI
  and tests) claims one job at a time.
* **Claiming:** `SELECT … ORDER BY priority, created_at LIMIT 1`; on PostgreSQL the query
  adds `FOR UPDATE SKIP LOCKED` so multiple workers are safe. SQLite runs a single worker.
* **Concurrency caps:** global `max_concurrent_runs`; **one active run per
  `repo_id + config_hash`** (`dedupe_key`) → a duplicate request gets `409 CONFLICT`.
* **Idempotency:** an `Idempotency-Key` header returns the existing job instead of a new
  one.
* **Cancellation** is cooperative: `POST /runs/{id}/cancel` sets `jobs.cancel_requested`;
  the orchestrator checks it between stages and raises `JOB_CANCELLED`.
* **Recovery:** `requeue_stale` returns jobs whose `heartbeat_at` is older than
  `job_heartbeat_timeout_seconds` to `QUEUED` (or `FAILED` once `max_attempts` is hit).
* **Retry:** only failures marked `retryable` (transient — e.g. GitHub 5xx / timeout) are
  requeued; everything else goes straight to `FAILED`.

A heavier broker (Celery/RQ/Arq) can be slotted behind `JobManager` later without touching
callers (§19).

---

## 5. Repository limits (§16)

Defaults in `RepositoryLimits`, all overridable via `ARCHON_LIMIT_*`:

| Limit | Default | Breach behaviour |
|---|---|---|
| `max_repo_size_bytes` | 500 MiB | **hard** — reject (`REPOSITORY_TOO_LARGE`), checked pre-clone from GitHub metadata and post-clone from disk |
| `max_file_size_bytes` | 2 MiB | _(declared; enforced in Phase 2 source analysis)_ |
| `max_file_count` | 20 000 | _(declared; Phase 2)_ |
| `max_git_history_commits` | 5 000 | **soft** — continue, record an `INFERENCE` evidence that archaeology will be truncated |
| `max_analysis_duration_seconds` | 1800 | used as the git subprocess timeout |
| `max_generated_tests` / `max_patch_candidates` / `max_sandbox_runtime_seconds` | 200 / 5 / 300 | _(declared; Phases 8–9)_ |
| `clone_depth` | 0 (full) | full history is kept for later archaeology; set >0 for shallow |

Nothing is ever silently dropped — a breach is either a structured rejection or a recorded
degradation (§16, §54).

---

## 6. Supported-repository contract (§17)

`archon/pipeline/support.py` classifies every checkout and stores the verdict +
machine-readable `support_notes` on the snapshot. The API and UI surface it; Phase 1 never
rejects on support level (an `UNSUPPORTED` repo still produces a snapshot with reasons).

| Level | Conditions |
|---|---|
| **SUPPORTED** | ≥1 Python file **and** Python ≥50 % of code files **and** a dependency manifest (`requirements.txt` / `pyproject.toml` / `setup.py` / `setup.cfg` / `Pipfile`) **and** >1 commit of history |
| **PARTIALLY_SUPPORTED** | has Python but fails one or more of the above — each shortfall is listed in `reasons` (low Python ratio → non-Python summarised only; no manifest → best-effort execution; shallow history → degraded archaeology) |
| **UNSUPPORTED** | no Python source files |

"No existing tests" is recorded as a reason but does not by itself downgrade the level —
characterization/generation can still establish baselines (§33).

---

## 7. Security posture (§52) — implemented in Phase 1

* **git** is always invoked as an argument list (`shell=False`), with
  `GIT_TERMINAL_PROMPT=0` / `GIT_ASKPASS` so a clone can never block on or leak
  credentials. stdout/stderr are redacted before entering a log or an `ArchonError`.
* **Secret redaction** (`core/logging`): URL-embedded credentials, `ghp_/gho_/…` tokens
  and any `*token* / *secret* / *password* / authorization` dict key are scrubbed from
  every log record.
* **GitHub token** is read from `ARCHON_GITHUB_TOKEN` only, embedded solely in the
  in-memory `clone_target`, and never written to `repositories.url`, an artifact, or a
  response.
* **Path traversal:** `Workspace.resolve_within` refuses any path that escapes the
  workspace root; workspace ids are ULIDs under a single configured root.
* **Workspace quota** is checked before each new checkout.

---

## 8. Sandbox threat model — _(declared; implemented Phase 7)_

All repository code, generated tests and generated patches are **UNTRUSTED** and will only
ever run inside an ephemeral Docker container: non-root, `--read-only` rootfs + tmpfs
work dir, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--network=none` by
default, `--cpus` / `--memory` (== `--memory-swap`) / `--pids-limit` / wall-clock kill,
empty environment (no ARCHON/Anthropic/GitHub secret ever passed in), `--rm` + a reaper
for orphans. A `Sandbox` ABC keeps room for a non-Docker driver. Static scanning of
generated diffs/tests happens *before* anything reaches the sandbox and *flags* rather
than silently drops.

---

## 9. Scoring engines — _(declared; implemented Phases 5–9)_

Legacy Risk, Change Safety, Hotspot, Repository Understanding and Patch Ranking will each
be a versioned module under `archon/scoring/` with an explicit signal set, normalisation,
weights in a versioned config, a formula, thresholds, categories, `explain()`, and
property-based acceptance tests (§5–7, §60). The `core/versions` registry already exists
to pin their versions onto each `AnalysisRun`.
