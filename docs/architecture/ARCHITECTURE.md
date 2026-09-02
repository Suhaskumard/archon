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
| `analysis/scoring` | Phase 5 - Legacy Risk, Hotspot, Repository Understanding, tech-debt detectors. Phase 6 - Change Safety, Change Impact. |
| `comparison` | Phase 11 - `differ` (deterministic diff of two runs across architecture / dependencies / Legacy DNA / risk / coverage / change safety), `store` (persist `RepositoryComparison` + report artifact). |
| `modernization` | Phase 12 - `planner` (the `MODERNIZING` stage): `assemble_targets` from the run's deterministic findings, AI `modernization_recommendation` for strategy/risk/effort/impact, deterministic `modernization.v1` safe ordering from the module import + change-safety graph. |
| `sandbox` | Phase 7 - `Sandbox` ABC, `DockerSandbox`, container reaper. |
| `testing` | Phase 7 - existing-test discovery (`discovery.py`). Coverage/gaps/characterization/generation are Phase 8. |
| `execution` | Phase 7 - runs a test suite through the sandbox, persists `Execution` + artifacts. |
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
| `risk_assessments` _(0005, Phase 5)_ | Generic engine-agnostic score row, reusable by any future scoring engine via `engine_version`. | `run_id`, `snapshot_id`, `component_id`, `engine_version`, `score`, `category`, `factor_breakdown` (JSON), `confidence`, `evidence_ids`, `produced_by` |
| `legacy_dna` _(0005, Phase 5)_ | Full Legacy Risk signal breakdown per component. | `run_id`, `snapshot_id`, `component_id` (unique per run), `age_days`, `complexity`, `churn`, `coupling`, `coverage`, `coverage_is_proxy`, `failure_count`, `assumption_count`, `debt_score`, `legacy_risk_score`, `category`, `confidence`, `factor_breakdown` (JSON) |
| `technical_debt_findings` _(0005, Phase 5)_ | One tech-debt detector hit. | `run_id`, `snapshot_id`, `component_id` (nullable), `category`, `location` (`path:line`), `evidence`, `severity`, `impact`, `confidence`, `recommendation`, `evidence_id` |
| `hotspots` _(0005, Phase 5)_ | Hotspot classification per component. | `run_id`, `snapshot_id`, `component_id` (unique per run), `score`, `classification`, `reasons` (JSON), `evidence_ids`, `engine_version` |
| `change_assessments` _(0006, Phase 6)_ | Change Safety score per component - standalone, not a `RiskAssessment` row (incompatible category vocabulary, see §14). | `run_id`, `snapshot_id`, `component_id`, `engine_version`, `safety_score`, `risk_category`, `factor_breakdown` (JSON), `recommended_preparation` (JSON list), `confidence`, `evidence_ids`, `produced_by` |
| `change_impacts` _(0006, Phase 6)_ | Change Impact traversal result per component - factual, not scored (no `confidence`/`evidence_ids`). | `run_id`, `snapshot_id`, `component_id` (unique per run), `direct_dependents`/`indirect_dependents`/`callers`/`related_tests`/`historical_co_changes`/`external_integrations` (JSON lists), `potential_impact` (JSON dict), `engine_version` |
| `test_cases` _(0007, Phase 7)_ | A test case, discovered or generated. Only `kind=EXISTING`/`origin=DISCOVERED` are produced this phase. | `run_id`, `snapshot_id`, `component_id` (nullable), `kind`, `path`, `name`, `body_ref`, `origin`, `validated`, `validation_errors` |
| `executions` _(0007, Phase 7)_ | One sandboxed run of a test suite. `kind` is `EnumString` (grows every later phase, like `Dependency.kind`). | `run_id`, `kind`, `sandbox_ref`, `command` (JSON), `exit_code`, `passed`/`failed`/`errors`, `timed_out`, `duration_ms`, `stdout_ref`/`stderr_ref`/`coverage_ref` (→ `analysis_artifacts.id`), `started_at`, `ended_at` |

`dependencies.kind` is a plain `VARCHAR` via the `EnumString` type decorator
(`db/types.py`), not a DB `CHECK` — the `DependencyKind` vocabulary grows every phase
(Phase 2: CONTAINS/IMPORTS/CALLS/INHERITS; Phase 3: DEPENDS_ON/TESTED_BY; Phase 4:
CHANGED_BY/CHANGED_WITH; later: FAILED_IN/FIXED_BY/AFFECTS) and validation happens at the
app boundary. Migration `0003` drops+recreates the (fully derived) `dependencies` table to
apply the widening.

Later phases add further tables as incremental migrations on
this baseline.

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
| `ANALYSIS_ONLY` / `FULL` | the full `STAGE_ORDER`: INGESTING → SNAPSHOTTING → … → ANALYZING_CHANGE_IMPACT → ANALYZING_TESTS → CHARACTERIZING → GENERATING_TESTS → EXECUTING → DETECTING_FAILURES → INVESTIGATING → GENERATING_PATCH → RANKING_PATCHES → VERIFYING_PATCH → REGRESSION_VERIFYING → RECORDING_INCIDENT → **MODERNIZING** |

As of Phase 12 **every** declared `Stage` is wired — `MODERNIZING` (the last one) runs
the modernization planner, so `_STAGE_PLANS[ANALYSIS_ONLY]` and `[FULL]` are the whole
`STAGE_ORDER` and `terminal_stage("FULL") == Stage.MODERNIZING`. Tests read the last
stage via `tests/conftest.terminal_stage(mode)` instead of pinning a literal, so
appending the final phase rippled through no test.

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

## 11. Sandbox threat model — implemented Phase 7 (§15); static-patch scanning declared

All repository code, generated tests and generated patches are **UNTRUSTED**. The Docker
sandbox itself (non-root, read-only rootfs, network isolation, resource limits, empty
environment, reaper) is implemented in Phase 7 - see §15 for the full detail. Static
scanning of AI-generated *tests* is implemented in Phase 8 (`testing/_safety.py`,
§16) - every generated test is parsed and scanned for banned constructs before it ever
reaches the sandbox. Static scanning of AI-generated *patches* (Phase 9) remains
declared-only: it will *flag* rather than silently drop, same as every other
degrade-not-silently-fail rule in this doc.

---

## 12. Scoring engines — Patch Ranking _(declared; implemented Phase 9+)_

Patch Ranking remains declared-only: it will be a versioned module under
`archon/analysis/scoring/` with an explicit signal set, normalisation, weights in a
versioned config, a formula, thresholds, categories, `explain()`, and property-based
acceptance tests (§5–7, §60), following the same shape Phases 5-6 established (§13-14).
The `core/versions` registry already exists to pin its version onto each `AnalysisRun`.

---

## 13. Scoring engines — Legacy Risk, Hotspot, Understanding, Tech Debt (Phase 5, §27-30)

Four deterministic engines - no AI - under `archon/analysis/scoring/`, run as the last
four stages of `ANALYSIS_ONLY`/`FULL`: `SCORING_UNDERSTANDING → BUILDING_LEGACY_DNA →
ANALYZING_TECH_DEBT → SCORING_HOTSPOTS`. All source their signals from data Phases 2-4
already persisted (`Component.metrics`, `assumptions`, `Dependency`).

**Legacy Risk** (`legacy_risk.v1`) - a weighted sum of normalized `[0,1]` signals
(complexity, churn, coverage-gap, coupling, assumption count, debt score, age), weighted
so churn + complexity + low coverage dominate (spec sec 7). `confidence` is the fraction
of signals backed by real data; coverage-gap is *always* a documented proxy this phase
(see below) and always counts against confidence, while historical failures (no data
until Phase 9) are omitted from the signal set entirely rather than defaulted to a false
"zero risk". Persists **both** a `LegacyDNA` row (the full signal breakdown - complexity,
churn, coupling, coverage, debt, age, confidence) and a `RiskAssessment` row
(`engine_version="legacy_risk.v1"`, generic score/category/confidence). `RiskAssessment`
is reusable by any future engine sharing its LOW/MODERATE/HIGH/CRITICAL vocabulary
(Patch Ranking, later); Change Safety (Phase 6, §14) uses an incompatible
SAFE/CAUTION/RISKY/DANGEROUS vocabulary and deliberately does **not** write here - see
§14's rationale. `LegacyDNA` stays Legacy-Risk-specific either way.

**Hotspot** (`hotspot.v1`) - the same normalized signal set, with a multiplicative
"signals overlap" bonus when ≥3 signals are independently elevated (spec sec 29). Runs
*last* in the stage order so it can reuse `LegacyDNA` rows for complexity/churn/coupling/
coverage and the **full** 13-detector `TechnicalDebtFinding` set (only available once
`ANALYZING_TECH_DEBT` has run) as its debt signal - a stronger signal than Legacy Risk's
own debt input (see the tech-debt ordering note below).

**Repository Understanding** (`understanding.v1`) - six evidence-coverage fractions
(architecture: % modules with a resolved role; dependency: % internal edges resolved;
behavior: % components with a behavior reconstruction; historical: git history span
capped at a "deep enough" threshold; testing: % modules with a `TESTED_BY` edge;
configuration: % config files parsed without error), averaged into an overall score, with
confidence tracking the same fractions (sparse evidence lowers both, spec sec 30). Cheap
pure aggregation - always recomputed, never cached across runs.

**Tech-debt detectors** (`tech_debt.v1`) - 13 categories. Six are pure lookups against
already-persisted data: `long_functions`/`large_classes` (stored `loc`/`method_count`),
`circular_dependencies`/`high_coupling` (Phase 3's `metrics.architecture`),
`dead_code_candidates` (Phase 2's CALLS/INHERITS edges), and `global_state` (reuses Phase
4's `assumptions` table heuristic verbatim - zero new AST code). The remaining seven
(`duplicate_logic`, `low_cohesion`, `deprecated_apis`, `hardcoded_config`, `broad_except`,
`silent_failure`, `magic_numbers`) run one new AST pass per source file. Findings persist
to `TechnicalDebtFinding`, resolved to the nearest enclosing component by line range when
the detector doesn't already know its `component_id`.

**Debt-score ordering** - the `Stage` enum fixes `BUILDING_LEGACY_DNA` before
`ANALYZING_TECH_DEBT`, so Legacy Risk cannot wait for the full detector pass. It computes
a **cheap 4-detector subset** (long functions, large classes, circular dependencies, high
coupling - all pure lookups, no fresh AST) internally for its own `debt_score` input.
`ANALYZING_TECH_DEBT` then runs and persists the full 13-detector set independently, and
`SCORING_HOTSPOTS` (last) consumes that full set. A deliberate, bounded scope decision,
not an oversight.

**Coverage proxy** - no real test-execution/coverage data exists until Phase 8. Every
`LegacyDNA.coverage` value this phase is a coarse proxy (`0.5` if the owning module has a
`TESTED_BY` edge, else `0.0`), flagged `coverage_is_proxy=True` and always counted as
defaulted in the confidence calculation - never presented as measured coverage.

**API:** `GET /runs/{id}/legacy-dna` (+ `/components/{id}/legacy-dna`),
`GET /runs/{id}/hotspots`, `GET /runs/{id}/technical-debt`,
`GET /runs/{id}/understanding`. **Frontend:** Repository Understanding, Legacy DNA,
Technical Debt, Hotspots.

---

## 14. Change Safety & Change Impact (Phase 6, §31-32)

Two more deterministic engines - no AI - under `archon/analysis/scoring/`, run as the
last two stages of `ANALYSIS_ONLY`/`FULL`: `ASSESSING_CHANGE_SAFETY →
ANALYZING_CHANGE_IMPACT`. Both source signals from data Phases 2-5 already persisted,
including - for the first time - a cross-engine read of *this run's own* Phase 5 rows.

**Change Safety** (`change_safety.v1`) - the sign convention is the inverse of every
other scoring engine: **higher = safer**, not riskier. Each negative-direction signal
(complexity, coupling, dependency centrality, caller risk, hidden assumptions, churn) is
inverted (`1 - normalized`) *before* weighting, so the weighted sum is natively a safety
sum rather than a risk-sum-then-`100 - x` - this keeps `explain()`'s per-factor
contributions directly interpretable ("how much this factor added to safety") and avoids
a second sign-flip bug surface. Coverage is used directly (already "higher = safer", no
inversion) and remains the same `TESTED_BY`-edge proxy Phase 5 used - always flagged and
always counted as defaulted for confidence. Historical change-success rate and
historical failures have no data until Phase 9+ and are omitted entirely from both the
signal set and the confidence denominator.

The one genuinely new signal is **callers-at-risk**: for each caller reached via a
Phase 2 `CALLS` edge, its *this-run* `LegacyDNA.category` (HIGH/CRITICAL) and
`Hotspot.classification` (RISKY/CRITICAL) - both Phase 5 tables, already populated
earlier in the same pipeline run - decide whether that caller counts as "at risk";
`caller_risk_ratio = at_risk_callers / total_callers`. Results persist to a **standalone**
`ChangeAssessment` table, not a `RiskAssessment` row: `RiskAssessment.category` is a
closed `_enum(RiskCategory)` (LOW/MODERATE/HIGH/CRITICAL), incompatible with Change
Safety's SAFE/CAUTION/RISKY/DANGEROUS vocabulary. Widening that column to a shared
`EnumString` would let two unrelated vocabularies collide in one query for no present
benefit, so `ChangeAssessment` gets its own table and category enum instead, exactly as
the plan doc's own data model specified. Snapshot-cached like Legacy Risk (clone from a
prior run over the same snapshot) - safe because the caller-risk signal it reads is
itself cloned identically when the snapshot is unchanged.

**Change Impact** (`change_impact.v1`) - for a target component, resolved to its owning
MODULE, reuses `analysis/graph/builder.py::build_module_graph` as-is (no new graph code):
direct dependents = `mg.predecessors(node)`, indirect dependents =
`nx.ancestors(mg, node) - direct - {node}` (edges point dependent→dependency, so a
node's ancestors are exactly its transitive dependents). Callers come from Phase 2
`CALLS` edges, related tests from Phase 3 `TESTED_BY` edges, historical co-changes from
Phase 4 `CHANGED_WITH` edges (read directly, no recomputation), and external
integrations from the module's own `external=True` Dependency rows. The "what could
break / which tests to run / what to do first" narrative is a deterministic template,
not AI - consistent with every Phase 5-6 engine.

**Pipeline stage vs. on-demand POST, reconciled:** the spec calls Change Impact out as
"for a selected component" with a `POST` verb, yet `ANALYZING_CHANGE_IMPACT` is a fixed
pipeline stage per `jobs/state_machine.py::STAGE_ORDER`. Resolution: the stage
precomputes a `ChangeImpact` row for every MODULE component (cheap - pure graph/query
reads, no AI, so no cost cap is needed the way Phase 4 capped AI calls);
`POST /runs/{id}/change-impact` accepts `{"component_id"}` and returns the existing row
if already computed, otherwise computes-and-upserts one on demand for any other
component (typically a FUNCTION/METHOD/CLASS). `ChangeImpact` itself has no run-to-run
caching (deliberately simpler than Change Safety's) - it's cheap enough to always
recompute, and the on-demand path only ever checks the current run's own rows.

**API:** `GET /runs/{id}/change-safety` (ascending by score - least-safe first),
`POST /runs/{id}/change-impact`. **Frontend:** Change Safety, Change Impact.

---

## 15. Secure execution / sandbox (Phase 7, §12, §36)

`archon/sandbox/` implements the threat model from §11 for real: `Sandbox` (ABC) +
`DockerSandbox`, shelling out to the `docker` CLI with argument lists (mirroring
`gitcli.py`'s safety conventions) rather than adding the `docker` Python SDK.

**`docker create` flags implementing every threat-model requirement**: `--user 1000:1000`,
`--read-only`, `--tmpfs /work:rw,uid=1000,gid=1000,size=128m` + `--tmpfs /tmp:...`,
`--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--network=none` by default,
`--cpus`/`--memory`==`--memory-swap`/`--pids-limit`, `--label archon.managed=true` (for
the reaper), empty environment (no `-e` flags at all - only the image's own `ENV`, which
sets none). Deliberately **not** `--ulimit nproc`: it is a per-real-UID kernel limit
shared across *every* container using that UID on the host, not a per-container control
- on a host already running other containers as uid 1000, a low nproc ulimit starved
unrelated containers before the sandboxed one even started. `--pids-limit` (a genuine
per-container cgroup control) is the correct and sufficient fork-bomb containment.

**Copy-in/copy-out uses `docker exec` + `tar`, never `docker cp`.** Empirically,
`docker cp` cannot see into tmpfs-mounted paths in either direction (it reads the
storage driver's layer diff, which tmpfs never joins), and separately refuses to write
into any `--read-only` container regardless of which mount the target path resolves to.
The workaround: the container's main process is a `sleep` placeholder (tmpfs mounts
aren't attached until `docker start`, so `docker cp` can't populate them pre-start
either); once running, the workspace is piped in as a tar stream via
`docker exec -i <id> sh -c 'tar -xf - -C /work'`, and results are piped out the same way
(`docker exec <id> tar -cf - -C /work/out .`). The real command's stdout/stderr are
redirected to files inside `/work` (not captured from the `docker exec` client) so they
survive even when the wall-clock timeout has to `docker kill` the container.

**Reaching `EXECUTING`.** `Stage`/`STAGE_ORDER` fix
`ANALYZING_TESTS → CHARACTERIZING → GENERATING_TESTS → EXECUTING` right after Phase 6's
stages. `ANALYZING_TESTS` does real, cheap work (`archon/testing/discovery.py`): a test
function is identified by its owning MODULE being flagged `is_test` (Phase 2 never sets
that flag on the FUNCTION/METHOD rows themselves) plus its own `test_`-prefixed name;
each becomes one `TestCase(kind=EXISTING, origin=DISCOVERED)` row. `CHARACTERIZING` and
`GENERATING_TESTS` were honest stubs in this phase - Phase 8 (§16 below) replaced both
with real work. `EXECUTING` (`archon/execution/runner.py::run_existing_tests`) builds
one `pytest -q --tb=short --junit-xml=... --cov=. --cov-report=xml:...` `ExecutionSpec`,
runs it through `DockerSandbox`, and persists one `Execution(kind=EXISTING_TESTS)` row
plus stdout/stderr/coverage/junit text artifacts (`core/artifacts.write_text`, a
non-JSON sibling of `write_json`) - `coverage.xml`/`junit.xml` were captured but not
parsed until Phase 8 (§16).

**Scope cuts**: the opt-in egress-filtered dependency-install phase is declared on
`ExecutionSpec.allow_install` but raises if requested - no fixture needs installed
third-party dependencies at sandbox-run time yet. `ExecutionKind` is a plain `VARCHAR`
(`EnumString`, like `Dependency.kind`) since it grows every later phase
(characterization, generated tests, patch verification, regression).

**API:** `GET /runs/{id}/tests`, `GET /runs/{id}/executions` (capped stdout/stderr
preview + artifact refs for the full text). **Frontend:** Test Execution.

---

## 16. Characterization & test-gap analysis (Phase 8, §33-35)

Replaces `CHARACTERIZING`/`GENERATING_TESTS`'s Phase 7 stubs with real work, and adds
real coverage-based test-gap ranking to `EXECUTING`. No new stages - `STAGE_ORDER` is
fixed and append-only, so Phase 8 fills the four already-reserved slots.

**Stage-sequencing resolution.** `EXECUTING` (which produces this run's own
`coverage.xml`) runs *after* `CHARACTERIZING`/`GENERATING_TESTS`, so those two stages
can't use this run's coverage to pick targets. Resolved by splitting responsibility by
data source rather than reordering stages: `ANALYZING_TESTS` computes a cheap
*structural* candidate list (`testing/gaps.py::identify_untested_components` - a
non-test FUNCTION/METHOD component with no discovered test whose name naively matches
it, e.g. no `test_reserve` for `reserve`); `CHARACTERIZING`/`GENERATING_TESTS` consume
that list (capped at 3 targets each, see below); `EXECUTING` runs the *combined* suite
(existing + characterization + AI-generated files, already copied into the workspace by
the earlier stages) and only then parses the real `coverage.xml` to compute
`TestGap` rows, joining this run's already-persisted `LegacyDNA.legacy_risk_score` /
`ChangeAssessment.safety_score` as the "prioritized by Legacy Risk / Change Safety"
signal (historical-failures prioritization is weighted 0 and documented as omitted -
no data until Phase 9).

**Characterization** (`archon/testing/characterization.py`, spec §33 Principle 14 -
observed behaviour is not assumed correct): target → `assess_target_safety` (rejects
decorated functions, `*args`/`**kwargs`, and source containing an obvious
side-effecting construct) → `generate_bounded_inputs` (deterministic uniform-value
sets per parameter: `0, 1, -1, ""`) → a small harness script is written into the
workspace and run once through the sandbox, importing the target fresh (clearing
`sys.modules` for its package) before every input to avoid state leaking between
calls → the observed `{input, returned, raised}` per input is hashed into a
`baseline_hash` and stored on `Characterization`, alongside an emitted pytest test
(`assert repr(call) == ...` or `with pytest.raises(...)`) persisted as
`TestCase(kind=CHARACTERIZATION, origin=CHARACTERIZATION)`.

**AI test generation** (`archon/testing/generation.py`, mock provider): one
`MockAIProvider._op_test_generation` call per candidate proposes up to six scenarios
(unit/boundary/invalid-input always; exception/integration/regression conditionally,
per `domain/ai_schemas.py::TestGeneration`) - deterministic, template-based, no real
type inference. Each scenario is **static-validated** individually (`ast.parse` +
the same banned-construct scan characterization uses, factored into
`testing/_safety.py`), then all statically-valid scenarios for one candidate are
combined into **one** file and **sandbox-validated together in a single container run**
- see the container-count note below for why not one container per scenario.
`validated=True` means "collected and ran", not "passed" - a scenario expecting an
exception is still valid if it ran, matching the spec's static+sandbox validation bar
rather than a correctness bar.

**Container-count discipline.** The first implementation spun one sandbox container
per AI scenario (up to 6) *and* one per characterization target (up to 5) - on Docker
Desktop, each container costs multiple seconds to create/start/copy-in/exec/copy-out/
remove, so a single FULL pipeline run could spawn 30+ containers and full-suite test
runs started hanging. Fixed by batching a candidate's scenarios into one sandbox run
(above) and capping both modules to 3 candidate targets per run
(`_MAX_TARGETS`) - roughly 7 containers per pipeline run total (3 + 3 + `EXECUTING`'s
1), in line with Phase 7's per-run cost. `DockerSandbox`'s `_create`/`_start`/copy-in/
copy-out calls also gained a 30s control timeout (previously unbounded - only `_exec`
had one) so an unresponsive daemon fails fast instead of hanging the pipeline.

**Test-gap analysis** (`archon/testing/gaps.py::analyze_test_gaps`, called from
`_executing`): parses `coverage.xml` (Cobertura format, `testing/coverage.py`;
`execution/runner.py`'s pytest command gained `--cov-branch`), computes per-component
`coverage_pct` by intersecting the component's line range against the file's
executable/covered line sets, and persists one `TestGap` row per component below full
coverage - `kind=UNTESTED_FUNCTION` at 0% coverage, `MISSING_EDGE_CASE` otherwise
(the other three declared `TestGapKind` values await a more precise future engine).
`priority_score` weights: legacy risk 0.4, change danger (`1 - safety_score/100`) 0.4,
coverage gap 0.2, historical failures 0.0 (documented, not faked).

**Scope cuts**: `LegacyDNA.coverage`/`ChangeAssessment.coverage` stay the documented
`TESTED_BY`-edge proxy from Phases 5-6 - retrofitting real coverage into those engines
would touch code whose acceptance tests pin exact numeric scores, for a gain
`TestGap.coverage_pct` already delivers directly. Characterization/generation target
only module-level `FUNCTION` components - `METHOD` targets need instance construction,
which this deterministic engine cannot safely infer; skips are evidence-backed
(`INFERENCE` rows), never silent.

**API:** `GET /runs/{id}/characterization`, `GET /runs/{id}/test-gaps` (sorted by
`priority_score` desc, optional `priority` filter). **Frontend:** Characterization,
Test Intelligence.

---

## 17. Failure investigation & self-healing (Phase 9, §37-43)

Closes the MVP loop with six stages filling `Stage`'s already-declared
`DETECTING_FAILURES → INVESTIGATING → GENERATING_PATCH → RANKING_PATCHES →
VERIFYING_PATCH → REGRESSION_VERIFYING` slots - no new stages added.

**MVP-loop stages fail the run, they don't degrade-and-continue.** Unlike Phase
8's AI-call handling (catch, downgrade to Evidence, continue), none of this phase's
orchestrator dispatch methods wrap their module calls in try/except - per the state
machine's own rule (§10), these are MVP-loop stages that propagate an internal error
to fail the run. A stage with genuinely no work (no failures, or no investigation
cleared the confidence gate) still completes normally with one FACT Evidence row.

**Failure detection** (`archon/failure/detection.py`) parses the `execution_junit`
artifact `execution/runner.py` has captured since Phase 7 but never read until now -
one `Failure` per failing/erroring `<testcase>`, with `path:line: in func` stack
frames extracted from pytest's `--tb=short` text and resolved to `Component` rows by
line-range containment. Each failure (capped at 3/run) is re-run once more through
the sandbox for a reproducibility check.

**Investigation** (`archon/investigation/engine.py`) assembles context - the
implicated `Component`, its `Assumption` rows - and calls the mock `root_cause_analysis`
AI op. Only investigations at `Confidence.MEDIUM`+ (`PATCH_GENERATION_CONFIDENCE_THRESHOLD`)
proceed to `GENERATING_PATCH`; a failure the mock can't explain gets
`confidence=UNKNOWN` and is honestly skipped (Evidence, not silence) - spec §38's
documented threshold gate.

**Patch generation** (`archon/healing/generation.py`) is deliberately scoped, like
every other Mock AI op, to one recognized bug pattern: an unguarded division, tied to
Phase 4's existing `division`-kind `Assumption` detector. Two deterministic candidates
per gated investigation - `guard_zero_divisor` (a real fix, AST-derived, mirroring the
sibling guard style already in the fixture) and `naive_integer_division` (a
deliberately wrong one) - so ranking/verification have a genuine choice to make,
matching the spec's own acceptance bar ("a deliberately bad candidate is rejected").
`old_snippet`/`new_snippet` are exact source text; application is a literal string
replacement, so **"applies cleanly" is a verified fact** (`source.count(old_snippet) == 1`),
never a claim - and a real unified diff (`difflib.unified_diff`) is computed and stored
as the artifact of record regardless. Static validation (`ast.parse`, the same
banned-construct scan Phase 8 built for generated tests, and a ≤20-changed-line
Minimal Patch Principle cap) is recorded on every `Patch` row, flagged not dropped,
mirroring §12's sandbox rule for generated *tests* onto generated *patches* too.

**Patch ranking** (`archon/healing/ranking.py`) is **deterministic, not another AI
call** - the spec's own language for it ("versioned, explainable... per doc") matches
`legacy_risk.py`'s shape exactly. Pre-verification rank (`rank_static`) gates on static
validation and scores by patch size alone - it only decides verification order.
Post-verification rank (`rank_verified`) is dominated by real pass/fail signals
(correctness weight 0.8, size 0.2) once they exist.

**Verification** (`archon/verification/engine.py`, spec §41-42) tries **every**
generated candidate (bounded - at most two per investigation), not just the top-ranked
one: an earlier version stopped at the first `VERIFIED` patch, but since the two mock
candidates can tie on the static-only pre-verification rank, whichever sorted first
would win immediately and silently skip verifying the other - hiding the rejection
story the acceptance bar wants demonstrated. Each candidate gets its own throwaway
`WorkspaceManager.clone()` (new method, `shutil.copytree` of the `repo/` dir) - the
original checkout every other stage uses is never touched (Principle 11). Three
sandbox runs per candidate: the originally-failing test alone
(`original_failure_fixed`), the full existing+characterization+generated suite
(`regression_pass`/`existing_tests_pass`, `new_critical_failures` = failures now
present that weren't in the pre-patch failing set), and characterization tests alone
(`characterization_pass`). `verdict = VERIFIED` only when every check is `True` and
the snippet swap applied cleanly (§41, verbatim AND). Rejection needs no explicit
"rollback" step beyond discarding the clone (`WorkspaceManager.cleanup`) - the original
was never mutated, so there is nothing to restore.

**Scope cuts**: only one bug pattern class is recognized (unguarded division) - a real
AI provider would generalize root-cause analysis and patch proposal without touching
the deterministic scaffolding (validation, ranking, verification) built this phase.
A `VERIFIED` patch is recorded as an `Incident` in Phase 10 (§18 below).

**API:** `GET /runs/{id}/failures`, `/investigations`, `/patches` (with
`diff_preview`, `state` filter, sorted by `rank_score` desc), `/verifications`.
**Frontend:** Failures, Root Cause Analysis, Self-Healing, Patch Verification.

---

## 18. Incident memory (Phase 10, §44)

`RECORDING_INCIDENT` was the penultimate `Stage`; Phase 12 wired the last one
(`MODERNIZING`), so `_ANALYSIS_STAGES` is now the complete `STAGE_ORDER`.

**Repository-scoped, not run/snapshot-scoped.** `Component`/`RepositorySnapshot` ids
change across commits, so `archon/incidents/store.py::compute_failure_signature`
deliberately excludes `component_id` and line numbers - it keys on `exception_type`
plus the innermost stack frame's `(path, func)`, which stays stable across commits of
the same repo. `find_similar_incidents(repo_id, signature)` therefore searches every
prior run of that repository, not just the current snapshot.

**Cited, never substituted (Principle 15).** `investigation/engine.py` looks up
similar incidents *before* every root-cause AI call and always records
`Investigation.cited_incident_ids` (empty if none) regardless of outcome. The mock
provider only appends one sentence to `reasoning_summary` naming the prior incident
id(s) when both history exists *and* the current evidence independently supports a
hypothesis - the hypothesis statement, confidence, and evidence set are computed
exactly as they would be with zero history. Verified directly by the acceptance test:
a second run's investigation confidence over the same bug is bit-for-bit identical to
the first run's, even though it cites the first run's incident.

**Schema note.** `Investigation.cited_incident_ids` required widening an existing
table - since `investigations` is fully-derived (rebuilt every run), the migration
reuses the exact drop-table-and-recreate-from-metadata pattern
`0003_architecture.py` already established for `dependencies`, rather than an
`ALTER TABLE`. `Incident.run_id` isn't in the spec's exact field list (mirroring the
`Patch.old_snippet`/`new_snippet` precedent from Phase 9) - added because an incident
otherwise has no run-scoped identity to clear on a resumed run's re-entry, even though
by design it's meant to outlive the run that created it.

**Recording** (`record_incidents`, called from `_recording_incident` - an MVP-loop
stage, no try/except): one `Incident` per `Patch` with `state == VERIFIED` this run,
pulling `root_cause` from the `Investigation`'s top hypothesis, `evidence_ids` from
this run's `INVESTIGATING`/`VERIFYING_PATCH` Evidence rows referencing that
investigation/patch, and `regression_test_ids` from the `TestCase` row matching the
original failing test plus any characterization test for the same component.

**Scope cut**: retrieval is exact-signature match only - the spec also mentions
"stack + component overlap" as a fuzzier signal, not needed while only one bug
pattern is recognized end-to-end.

**API:** `GET /runs/{id}/incidents` (recorded by this run), `GET
/repositories/{id}/incidents` (full repo history, `created_at` desc). **Frontend:**
Incident Memory.

---

## 19. Repository comparison (Phase 11, §45)

**On-demand, not a pipeline stage.** Comparison is intrinsically cross-run - it needs
two runs that already exist - so, like `POST /runs/{id}/change-impact`, it is computed
on request rather than wired into the single-run `Stage` machine. No `Stage`,
`STAGE_ORDER`, `_ANALYSIS_STAGES`, or `PipelineResult` change; nothing that pins
`terminal_stage` shifts.

**Keyed by `qualified_name`, not `component_id`.** Component ids are snapshot-scoped
and differ between commits; `archon/comparison/differ.py` builds a per-snapshot
`{component_id -> qualified_name}` map and diffs every section on the stable name (the
same reasoning incident signatures use). Sections: architecture (modules added /
removed / role changes), dependencies (`src -kind-> dst` edges added / removed),
Legacy DNA (per-component `legacy_risk_score` / `debt_score` deltas + `RiskCategory`
transitions), generic risk (`RiskAssessment`, when present), coverage (the Legacy-DNA
**proxy** value - flagged `is_proxy`), technical debt (findings added / resolved,
matched on `(qualified_name, category, location)`), and change safety
(`safety_score` delta + `ChangeSafetyCategory` transition; a score *drop* is the
regression, since higher = safer). `summary` rolls the section counts plus the union
of risk-category regressions up for list views.

**Inputs, not completion.** The API accepts any run that has a snapshot and a
`last_completed_stage` at or past `ASSESSING_CHANGE_SAFETY` - every diffed table is
populated by then, so a run that later failed an MVP-loop stage is still comparable.
`base_run_id == head_run_id`, cross-repository runs, and not-yet-scored runs are
`409`s.

**Persistence.** One `repository_comparisons` row per ordered `(base_run, head_run)`
pair (`uq_comparison_run_pair`), upserted on recompute - `summary` + full `report` as
JSON columns, and the full report also written to disk as an `AnalysisArtifact`
(`kind = repo_comparison_<comparison_id>`, owned by the head run) for the spec's
"report as artifact". Engine version `comparison.v1`.

**API:** `POST /repositories/{id}/comparisons` `{base_run_id, head_run_id}` (returns
the cached row if the pair was already compared), `GET /repositories/{id}/comparisons`
(summaries, `created_at` desc), `GET /comparisons/{id}` (full report). **Frontend:**
Repository Comparison panel in the run view - pick a baseline run, get the delta
tables.

**Scope cut**: no Excel "Comparison" sheet - all Excel reporting (§49-50) is still
unbuilt as of Phase 11.

---

## 20. Modernization (Phase 12, §46)

The final phase. `MODERNIZING` was the one declared `Stage` never in the orchestrator's
`_ANALYSIS_STAGES`; wiring it is a one-line append, after which
`terminal_stage("FULL") == Stage.MODERNIZING` and every `last_completed_stage` assertion
in Phases 2-11 follows automatically (they read `tests/conftest.terminal_stage`, never a
literal).

**Deterministic targets, AI strategy, deterministic order.** `modernization/planner.py`:

1. `assemble_targets` - every non-test **module** with a modernization-worthy signal
   (legacy category >= MODERATE, any `TechnicalDebtFinding`, a WATCH+ `Hotspot`, or
   membership in an import cycle), with its signals rolled up from the run's `LegacyDNA`
   / `Hotspot` / `ChangeAssessment` rows and its components' tech-debt findings.
2. AI `modernization_recommendation` (mock) picks `strategy` / `risk` / `effort` /
   `impact` / `rationale` per target from a **fixed finding->strategy mapping**
   (coverage gap + HIGH/CRITICAL -> `add_tests`; cycle / `CIRCULAR_DEPENDENCY` ->
   `extract_dependency`; `DEPRECATED_API` -> `replace_dependency`; complexity/coupling or
   a structural smell -> `refactor`; `rewrite` only for a `CRITICAL` target when nothing
   cheaper applied - Principle 12). Wrapped in `try/except (AIProviderError,
   AIOutputError)` -> degrade-and-continue (a FACT Evidence + empty plan), never a failed
   run, because modernization is advisory analysis, not the MVP loop.
3. `compute_safe_order` (`modernization.v1`, deterministic + explainable) reuses
   `build_module_graph` + `nx.condensation` (so the fixture's deliberate import cycle
   doesn't break the topological sort), orders SCCs dependencies-first, then within a
   generation sorts by `(strategy_rank, -change_safety_score, legacy_risk_score, target)`
   - `add_tests` (0) < `extract_dependency`/`replace_dependency` (1) < `refactor` (2) <
   `rewrite` (3). Assigns contiguous `order_index`.

**Persistence.** One `modernization_recommendations` row per plan step (`target`,
`strategy`, `risk`/`effort`/`impact`, `order_index`, `rationale`, `dependencies` =
in-plan modules this target imports, `required_tests`, `prerequisites`,
`change_safety_ref`, `confidence`, `classification`, `ai_schema_version`,
`evidence_ids`), plus one `RECOMMENDATION` `Evidence` row per step whose `refs` carry
the ordering `breakdown`. Idempotent re-entry (`delete WHERE run_id=?` first). Engine
versions `modernization.v1` + `ai_modernization_recommendation` =
`modernization_recommendation.v1`.

**API:** `GET /runs/{id}/modernization` (rows ordered by `order_index`, optional
`strategy` filter, 404 on unknown run / 409 on a snapshot-less run). **Frontend:**
Modernization panel in the run view - the ordered table with strategy pills, risk /
effort / impact, and the plan's confidence + classification.

**Scope cut**: no Excel "Modernization" sheet - all Excel reporting (§49-50) remains
unbuilt. No manifest-level deprecated-dependency scan (maps onto AST `DEPRECATED_API`
findings only). Recommendations are advisory - nothing is auto-applied (Principle 11).

---

## 21. Reporting & bulk I/O (Phase 13, §49-50)

**Excel report.** `GET /runs/{id}/report.xlsx` (the codebase's first binary endpoint)
returns `ARCHON_Legacy_Analysis.xlsx` - 14 sheets (Executive Summary, Repository
Understanding, Architecture, Legacy DNA, Change Safety, Change Impact, Technical Debt,
Test Gaps, Characterization, Failures, Repairs, Modernization, Software Archaeology,
Incident Memory). `archon/reporting/workbook.py::build_report` renders each sheet from
`archon/reporting/queries.py`, which is a **thin adapter that calls the existing API
router functions directly** (all args explicit) - the report and the JSON API share one
data path, no separate engine (§49). Artifact-backed resources (understanding,
architecture, evolution) that raise `CONFLICT` before their stage runs are caught and
rendered as "not scored", so a partial run still yields a full workbook. The bytes are
also persisted as an `AnalysisArtifact` via the new `core/artifacts.write_bytes`.
`queries._r()` imports the routers lazily to avoid a `reporting <-> api.app` cycle.

**Bulk input.** `POST /repositories/bulk` (multipart) and `archon bulk-import <xlsx>`
call `archon/reporting/bulk_import.py::import_repositories_xlsx`. Columns: `Repository
URL`, `Branch`, `Analysis Mode`, `Priority`. Each row reuses `provider_for` +
`RepositoryProvider.parse` for deterministic validation, upserts a `Repository`, and
enqueues an ordinary run through `JobManager.create_run_with_job(priority=...)` - the
same path as `POST /repositories/{id}/runs`, no new enqueue code. Per-row outcome is
`created` / `skipped` (dedupe of an in-flight `repo+config`) / `error` (bad URL / mode /
priority).

**CLI:** `archon report <run_id> [--out]`, `archon bulk-import <xlsx>`. **Frontend:**
`api.downloadReport` (blob download) + a "Download report (.xlsx)" button on a COMPLETED
run. **Deps:** `openpyxl>=3.1`, `python-multipart>=0.0.9` (core).

**Scope cut:** the routers still hold their own inline `select` + `*Out` mappers -
consolidating them onto `queries.py` is Phase 15's de-duplication work; `queries.py`
calling them as-is already satisfies "one data path".

---

## 22. Test & CI hardening (Phase 14)

**`RunMode.ANALYSIS_ONLY` now stops at `ANALYZING_TESTS`** (the last sandbox-free stage;
`CHARACTERIZING` is the first that needs the Docker sandbox). `RunMode.FULL` is still the
whole `STAGE_ORDER` through `MODERNIZING`. `_ANALYSIS_ONLY_STAGES =
_ANALYSIS_STAGES[:index(CHARACTERIZING)]` in `pipeline/orchestrator.py`;
`conftest.terminal_stage("ANALYSIS_ONLY")` resolves to `Stage.ANALYZING_TESTS`
automatically. Effect: **the entire deterministic-analysis + scoring + test-discovery
pipeline is Docker-free-testable**. ~24 test files whose assertions only read
analysis/scoring rows were switched from `FULL` to `ANALYSIS_ONLY`; the
execution/characterization/healing/incidents API tests gained an autouse
`_needs_sandbox` fixture so they *skip* (not fail) without `archon-sandbox:latest`.

**`tests/acceptance/test_end_to_end.py`** — the spec's single named e2e test
(Docker-gated): one `FULL` run over `build_test_repo`, asserting a real row at every
stage boundary (snapshot SHA -> components/deps -> 3 commits -> a module with an
inferred role -> Legacy-DNA/Hotspot/Change-Safety -> the planted `TestGap` on
`inventory.reserve` -> the planted `ZeroDivisionError` -> investigation names `divide`
-> a `VERIFIED` patch with `regression_pass` -> one `Incident` -> a `Modernization`
plan -> `build_report` renders 14 sheets).

**`tests/unit/test_schema_drift.py`** — `alembic.autogenerate.compare_metadata(migrated
DB, Base.metadata)` must have no *structural* diff (`add_table` / `add_column` /
`add_constraint` / …). The migrations build tables from live model metadata via
`create_all(tables=[...])`, so a fresh DB always matches - but a production DB migrated
before a model gained a column would silently diverge; this catches that. SQLite's lossy
`modify_type` / `modify_default` reflection on `EnumString` / `_enum` VARCHAR + bool is
filtered out.

**`tests/unit/test_scoring_properties.py`** — Hypothesis proofs for `legacy_risk`,
`hotspot`, `change_safety`, `understanding`: `0 <= score <= 100`, `0 <= confidence <= 1`,
category in the enum, and monotonicity in every signal (with the §7 "more coverage lowers
risk" exception). Complements the hand-picked ordering tests.

**CI:** `make ci` = `lint` + full `pytest` (Docker tests skip) + `frontend-check`
(`npm ci && typecheck && build`). `.github/workflows/ci.yml` runs three jobs: `backend`
(no-Docker pytest), `frontend`, and `full-suite-docker` (`make sandbox-image` + full
pytest). `hypothesis>=6` added to `[dev]`; `[tool.coverage]` config for `make cov`.
