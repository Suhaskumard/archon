# ARCHON Architecture (living document)

This records the architectural decisions that are **implemented** as of Phase 3, plus the
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
| `core` | `ids` (ULID), `errors` (taxonomy), `logging` (structured + secret redaction), `versions` (engine-version registry), `artifacts` (fs artifact store). |
| `domain` | Enums / value objects: `Classification`, `Confidence`, `RunState`, `JobState`, `Stage`, `SupportLevel`, `RunMode`, `ProviderKind`, `DependencyKind`; `ai_schemas` (pydantic AI output contract). |
| `db` | SQLAlchemy models, engine/session, `migrate` (programmatic Alembic), `types.EnumString`. |
| `analysis/source` | Phase 2 - `ast`-based extractor: components, dependencies, complexity, entry points, resolution. |
| `analysis/git` | Phase 4 - `git log` parse, churn/age/co-change, `CHANGED_WITH` / `CHANGED_BY` edges. |
| `analysis/graph` | Phase 3 - NetworkX component + module graphs; derives `DEPENDS_ON` / `TESTED_BY`; cycle detection. |
| `analysis/architecture` | Phase 3 - role inference (`roles.v1`) + coupling/centrality metrics + layering check + graph artifact. |
| `analysis/archaeology` | Phase 4 - deterministic behaviour facts + hidden-assumption heuristics + the first AI step. |
| `providers/repo` | `RepositoryProvider` ABC, `LocalRepositoryProvider`, `GitHubRepositoryProvider`, `gitcli` safe wrapper. |
| `providers/ai` | Phase 4 - `AIProvider` ABC + validation pipeline, `MockAIProvider` (deterministic, offline), `get_ai_provider()`. |
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
| `components` _(0002, Phase 2)_ | A source entity (file/module/class/function/method). Keyed to the **snapshot** so extraction is reused across runs. | `snapshot_id`, `parent_id` (CONTAINS tree), `kind`, `name`, `qualified_name`, `path`, `start_line`/`end_line`, `metrics` (Phase 3 adds `metrics.architecture`; Phase 4 adds `metrics.git`), `attributes`, `is_test`/`is_entrypoint`/`is_config`, `role` (set in Phase 3) |
| `dependencies` _(0002; 0003 widens `kind`)_ | A directed edge between components / modules. | `snapshot_id`, `src_component_id`, `dst_component_id` (null = unresolved), `kind`, `target_name`, `resolved`, `external`, `source_line`, `attributes` |
| `commits` _(0004, Phase 4)_ | A git commit reachable from the snapshot's HEAD. Keyed to the **snapshot**. | `repository_id`, `snapshot_id`, `sha` (unique per snapshot), `author_name/email`, `authored_at`, `committed_at`, `message`, `files_changed`, `insertions`, `deletions`, `is_merge`, `parents`, `changed_paths` |
| `assumptions` _(0004, Phase 4)_ | One detected hidden assumption. | `run_id`, `snapshot_id`, `component_id`, `kind`, `description`, `location` (`path:line`), `risk`, `confidence`, `suggested_test`, `produced_by`, `evidence_ids` |
| `behavior_reconstructions` _(0004, Phase 4)_ | Reconstructed behaviour + historical intent per component. | `run_id`, `snapshot_id`, `component_id` (unique per run), `purpose`, `historical_context`, `current_role`, `inputs/outputs/side_effects/exceptions/callers/callees/tests/likely_invariants` (JSON), `git`, `classification`, `confidence`, `produced_by` |

`dependencies.kind` is a plain `VARCHAR` via the `EnumString` type decorator
(`db/types.py`), not a DB `CHECK` — the `DependencyKind` vocabulary grows every phase
(Phase 2: CONTAINS/IMPORTS/CALLS/INHERITS; Phase 3: DEPENDS_ON/TESTED_BY; Phase 4:
CHANGED_BY/CHANGED_WITH; later: FAILED_IN/FIXED_BY/AFFECTS) and validation happens at the
app boundary. Migration `0003` drops+recreates the (fully derived) `dependencies` table to
apply the widening.

Later phases add `risk_assessments`, `legacy_dna`, … as incremental migrations on this
baseline.

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

**Which stages run** is chosen by `run.mode` (`pipeline/orchestrator.py::_STAGE_PLANS`):

| mode | executed stages |
|---|---|
| `INGEST_ONLY` | INGESTING → SNAPSHOTTING |
| `ANALYSIS_ONLY` / `FULL` | INGESTING → SNAPSHOTTING → ANALYZING_SOURCE → ANALYZING_GIT → BUILDING_GRAPH → RECONSTRUCTING_ARCHITECTURE → ARCHAEOLOGIZING _(+ later phases)_ |

Implemented stages today: **INGESTING**, **SNAPSHOTTING**, **ANALYZING_SOURCE**,
**ANALYZING_GIT**, **BUILDING_GRAPH**, **RECONSTRUCTING_ARCHITECTURE**, **ARCHAEOLOGIZING**.
Tests read the last stage via `tests/conftest.terminal_stage(mode)` instead of pinning a
literal, so a new phase no longer ripples through every test.

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

## 8. Source intelligence (Phase 2, §22)

`analysis/source/` extracts a Python checkout with the standard-library `ast` module —
no third-party parser. Two passes: build the module-name index, then parse each module and
resolve raw import/inherit/call records into edges against that index.

**Components** (`ComponentKind`): `FILE` (every `.py` plus recognised config files),
`MODULE` (per `.py`, dotted name, `src/` stripped), `CLASS`, `FUNCTION` (module-level and
nested up to depth 3), `METHOD`. Every component keeps `path` + `start_line`/`end_line`.
`metrics` holds numbers — `complexity`, `loc`, `sloc`, `param_count`, `args`,
`decorators`, `returns_annotation`, `is_async`, `is_generator`, `raises`, `has_docstring`
(classes add `method_count`; modules add module-level `complexity`). `attributes` holds
`is_package`, `is_test`, `parse_error`, `bases`, …; `is_test` / `is_entrypoint` /
`is_config` are also promoted to indexed columns.

**Cyclomatic complexity** (`complexity.v1`, documented in `complexity.py`):
`1 + if/elif + for + while + except + with-item + (BoolOp values − 1) + comprehension
for/if + ternary + match-case + assert`. Each callable is measured on its own body;
nested defs/classes are excluded and measured separately.

**Edges** (`DependencyKind`): `CONTAINS` (from the parent tree), `IMPORTS`
(module→module; imported names in `attributes`), `INHERITS` (class→class), `CALLS`
(callable→callable, incl. `self.method()` and `Name()` constructors). Resolution is
**conservative**: `resolved=True` only when the target is a real component in the
snapshot; unresolved references to something the module explicitly imported are kept
(`external=True`, `dst=None`); unresolved bare names (locals, builtins, duck-typed
attribute calls) are dropped.

**Entry points:** `if __name__ == "__main__"` guards, declared `console_scripts`
(pyproject `[project.scripts]` / entry-points, setup.cfg, best-effort setup.py), and
framework signals (`uvicorn.run`, `FastAPI(`, `Flask(`).

**Caching (§53):** components/dependencies are keyed to the immutable snapshot. A second
run over the same commit does **not** re-parse — the stage records "reused cached source
analysis". Syntax errors, oversize files and a file-count breach are recorded as
`INFERENCE` evidence / `degraded` and never abort the run.

**API:** `GET /snapshots/{id}/components` (filter `kind`, `path`, `is_test`,
`is_entrypoint`, `q`), `GET /components/{id}` (with child + edge counts),
`GET /snapshots/{id}/dependencies` (filter `kind`, `resolved`, `external`, `src`),
`GET /runs/{id}/source` (summary).

---

## 9. Architecture reconstruction (Phase 3, §23)

Two stages turn the flat component model into an architecture. Both are deterministic and
cached on the snapshot (roles + `metrics.architecture` live on `Component`).

**`BUILDING_GRAPH`** (`analysis/graph/`)

* `build_component_graph` - a `nx.MultiDiGraph` of every component + resolved dependency.
* `build_module_graph` - collapses to a `nx.DiGraph` of MODULE nodes: module A → module B
  when any component of A has a resolved IMPORTS/CALLS/INHERITS edge into B (internal
  only); edge `weight` = contributing count, `kinds` = which kinds contributed.
* `derive_edges` (idempotent per snapshot) persists **`DEPENDS_ON`** (one per module-graph
  edge) and **`TESTED_BY`** (for a test module T depending on non-test module M → `M → T`).
* `find_cycles` - `strongly_connected_components` + `simple_cycles` (capped at 50) + self
  loops; import cycles are emitted as `INFERENCE` evidence.

**`RECONSTRUCTING_ARCHITECTURE`** (`analysis/architecture/`)

* `roles.py` (`roles.v1`) - an explicit ordered decision procedure assigning one role per
  module: `test → config → entrypoint → api → cli → model → io → util → domain → unknown`.
  Signals: the `is_test` / `is_entrypoint` flags, name/path tokens, imported top-level
  roots, function/method decorators, and the class-vs-function mix. Keyword lists live in
  the module. The module's role is mirrored onto its FILE/CLASS/FUNCTION/METHOD
  descendants; recognised config files get `role="config"`.
* `metrics.py` (`arch_metrics.v1`) - per module: `fan_in`, `fan_out`,
  `instability = fan_out/(fan_in+fan_out)`, degree/betweenness centrality, PageRank
  (pure-Python, no numpy), `in_cycle` / `scc_size`, and `dependents` / `dependencies`
  name lists. Stored in `Component.metrics["architecture"]` for MODULE rows.
* **Layering check** - conservative: flags an edge only when a lower layer
  (`domain`/`model`/`io`/`util`/`config`) depends on `api`/`cli`/`entrypoint`, or a
  non-test module depends on a test module. Violations are `INFERENCE` evidence.
* **Artifact** - `core/artifacts.write_json` stores
  `<artifact_root>/<run_id>/architecture_graph.json` (`schema: archon.graph.v1`:
  node-link component + module graphs, roles, module metrics, cycles, violations) and
  upserts one `analysis_artifacts` row with a sha256 + size.

**API:** `GET /runs/{id}/architecture` (role histogram + module metrics + cycles +
violations + top hubs), `GET /runs/{id}/architecture/graph` (the raw artifact),
`GET /snapshots/{id}/modules` (MODULE rows with role + metrics; `role` / `in_cycle`
filters). `GET /snapshots/{id}/dependencies` now also serves `DEPENDS_ON` / `TESTED_BY`.

---

## 10. Software archaeology & the AI provider (Phase 4, §24-26)

Two deterministic-first stages plus the project's first AI step.

**`ANALYZING_GIT`** (`analysis/git/`)

* `history.read_history` parses `git log --numstat` via the safe `gitcli.run_git`;
  US/RS control bytes separate records so a commit message cannot break the parser.
  Bounded by `limits.max_git_history_commits` (soft; truncation → `INFERENCE` evidence).
* `metrics.compute_git_stats` → per path: churn (Σ ins+del), commit_count, first/last
  seen, `age_days` (anchor = snapshot ingest time), distinct authors. Co-change counts
  every unordered pair of `.py` files changed together, skipping package `__init__.py`
  and bulk commits (> 30 files); `confidence = count / min(commit_count)`.
* `persist.analyze_git` writes `commits`, sets `Component.metrics["git"]` on FILE + MODULE
  rows, and emits `CHANGED_WITH` (module↔module, both directions, `attributes` count +
  confidence) and `CHANGED_BY` (component → `dst=NULL`, `target_name`=sha, capped 20/comp).
  Cached per snapshot (commit rows + `metrics.git` present).

**`ARCHAEOLOGIZING`** (`analysis/archaeology/`)

* `assumptions.detect_assumptions` — conservative AST heuristics per function:
  `division` (÷ by an unguarded param), `global_state` (reads/mutates a module-level
  mutable global), `dict_key` (`d[k] -= …` with no membership check), `environment`
  (`os.environ[...]` / `os.getenv(x)` no default), `timezone` (naive `datetime.now()`),
  `empty_collection` (`x[0]` / `min(x)` on an unchecked param), `null` (param `.attr`
  deref with no `None` guard; `self`/`cls` never flagged). Each stays quiet when guarded.
* `behavior.reconstruct_behavior` — deterministic facts from AST metrics + CALLS/TESTED_BY
  edges + `metrics.git`: inputs, outputs, side effects (calls into `io`/`model` modules,
  async/generator), exceptions (own + 1-level propagated), callers, callees, tests,
  invariant hints.
* `reconstruct.run_archaeology` — the AI step: for each assumption and each target
  component (all modules + top functions by churn·complexity, capped at
  `ai_max_components_per_run`) it calls the provider for `assumption_analysis`,
  `historical_intent`, `behavior_analysis`. Persists `assumptions` +
  `behavior_reconstructions`, writes the `archaeology` artifact, emits a FACT summary +
  one `HYPOTHESIS` per high-risk assumption. Cached per snapshot by copying the prior
  run's rows.

**AI provider** (`providers/ai/`, spec §13-14)

* `AIProvider.complete_structured(operation, schema, context)` — the subclass returns a
  raw dict; the base class pydantic-validates it (`AIOutputError` on failure), then runs
  **evidence validation**: every `EvidenceRef` whose `ref` is not in
  `context["known_refs"]` is dropped and, if any were dropped, confidence is floored to
  `LOW`. AI never invents a component/commit/file/test.
* `MockAIProvider` — pure function of the context: no network, no randomness, same input
  → same output. It rephrases + classifies what the deterministic engines already found
  (e.g. assumption `risk` = per-kind base, bumped by churn and missing tests).
* `get_ai_provider()` reads `settings.ai_provider` (`"mock"` default). The provider name is
  pinned into `run.engine_versions["ai_provider"]`; a `claude` value raises until wired.
* Schemas live in `domain/ai_schemas.py` (`HistoricalIntent`, `BehaviorAnalysis`,
  `AssumptionAnalysis`, common `AIEnvelope`), each with a `*_SCHEMA_VERSION`.

**API:** `GET /runs/{id}/evolution` (commit count, span, authors, monthly timeline, top
churn, top co-change), `GET /snapshots/{id}/commits`, `GET /components/{id}/history`
(git metrics + its commits + co-change neighbours), `GET /runs/{id}/behavior` &
`GET /components/{id}/behavior`, `GET /runs/{id}/assumptions` (filter `kind` / `risk` /
`component_id`).

---

## 11. Sandbox threat model — _(declared; implemented Phase 7)_

All repository code, generated tests and generated patches are **UNTRUSTED** and will only
ever run inside an ephemeral Docker container: non-root, `--read-only` rootfs + tmpfs
work dir, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--network=none` by
default, `--cpus` / `--memory` (== `--memory-swap`) / `--pids-limit` / wall-clock kill,
empty environment (no ARCHON/Anthropic/GitHub secret ever passed in), `--rm` + a reaper
for orphans. A `Sandbox` ABC keeps room for a non-Docker driver. Static scanning of
generated diffs/tests happens *before* anything reaches the sandbox and *flags* rather
than silently drops.

---

## 12. Scoring engines — _(declared; implemented Phases 5–9)_

Legacy Risk, Change Safety, Hotspot, Repository Understanding and Patch Ranking will each
be a versioned module under `archon/scoring/` with an explicit signal set, normalisation,
weights in a versioned config, a formula, thresholds, categories, `explain()`, and
property-based acceptance tests (§5–7, §60). The `core/versions` registry already exists
to pin their versions onto each `AnalysisRun`.
