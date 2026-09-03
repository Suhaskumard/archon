# Phase 19 — Real `ClaudeAIProvider` + GitHub push webhook — Completion Record

Per `docs/ROADMAP.md` Phase 19. Closes the last two spec items (§13–14 real AI driver, §51
webhook) and lights up the "triggered by push `<sha>`" badge deferred from Phase 18. **The
mock AI provider stays the default and the only provider the test suite / offline dev use.**

## Scope delivered

| Area | Detail |
|---|---|
| **`ClaudeAIProvider`** | `archon/providers/ai/claude.py` — the real driver behind the unchanged `AIProvider` ABC. Only `_generate` is implemented; `base.py`'s pydantic validation + `_validate_evidence()` hallucination control (drop unresolved refs, floor confidence) run unchanged on its output. Structured output is forced with a single Anthropic **tool** whose `input_schema` is the operation's `schema.model_json_schema()` (titles stripped, `additionalProperties:false`, `tool_choice` pins it) — Claude must call it, so the raw result is already schema-shaped. Per-operation prompt renderers (`_ctx_*`) pull exactly the fields the mock `_op_*` consumes; `_SYSTEM_BASE` + a per-op rule paragraph mirror the mock docstrings. Token budget via `_clip_context` (halve the largest list field until under `ai_max_context_chars`). `_with_retries` maps SDK errors: timeout/connection/rate-limit/`{408,409,429,500,502,503,529}` → transient retry (`min(2**n,8)+jitter`) then `AIProviderError` (TRANSIENT); 400/422 → `AIOutputError`; 401/403/404 → `AIProviderError` (config). |
| **Optional dependency** | New `[project.optional-dependencies] claude = ["anthropic>=0.40,<1"]` (mirrors `postgres`). `claude.py` imports `anthropic` lazily; a mock-only install still imports the module, and `ClaudeAIProvider()` raises a clear `ArchonError` ("pip install -e 'backend[claude]'") if the SDK is absent. `dev` stays mock-only — CI never pulls the SDK. |
| **Settings** | `config.py`: `ai_model` (`claude-sonnet-5`), `ai_timeout_seconds` (60), `ai_max_retries` (2), `ai_max_output_tokens` (4096), and `anthropic_api_key: Field(validation_alias="ANTHROPIC_API_KEY")` (un-prefixed, as `.env.example` reserved). `github_webhook_secret` next to `github_token` (`ARCHON_GITHUB_WEBHOOK_SECRET`, env only). `.env.example` updated with an `ARCHON_AI_PROVIDER=mock` block + the webhook-secret line. |
| **Wiring** | `providers/ai/__init__.py`: the `"claude"` branch now `return ClaudeAIProvider()` (local import keeps `anthropic` out of the mock import graph). `current_versions()` already stamps `engine_versions["ai_provider"]`, so a claude run records `"claude"` for free. |
| **AI evidence trail** | `base.py` gains `AICallRecord` + a module `_AI_CALL_LOG` + `drain_ai_calls()`. `complete_structured` appends a record **only when `self.name != "mock"`** (guard keeps every existing test's Evidence count byte-identical). The orchestrator drains it into `Evidence(produced_by="claude:<model>")` after `ARCHAEOLOGIZING` / `GENERATING_TESTS` / `INVESTIGATING` / `GENERATING_PATCH` / `MODERNIZING` (idempotent — `_clear_stage` wiped that stage's Evidence on entry) and once at the top of `run()` to drop cross-run stragglers. |
| **`RunMode.INCREMENTAL`** | New enum value. `AnalysisRun.mode` moves from `_enum(RunMode)` (VARCHAR + CHECK) to `EnumString(RunMode)` (plain VARCHAR, validation at the Python boundary) — the `Dependency.kind` decision, so future `RunMode` values never need a CHECK migration. |
| **INCREMENTAL stage plan** | `_INCREMENTAL_STAGES` (9): ingest → snapshot → source → git → graph → architecture → change-safety → change-impact → test-discovery. A strict increasing subsequence of `_ANALYSIS_ONLY_STAGES` (legal for `enter_stage`), every stage already has a dispatch branch → no orchestrator changes beyond the plan entry. **Sandbox-free and makes zero AI calls** (`ARCHAEOLOGIZING` + the pure scoring engines skipped; `run_change_safety` reads their rows via `.get()`/`Counter` and degrades cleanly). `terminal_stage("INCREMENTAL")` auto-resolves to `ANALYZING_TESTS`. |
| **Targeted scoping** | `archon/analysis/incremental/scope.py::resolve_changed_components` maps webhook changed paths → component ids in the new snapshot. `run_change_impact` and `identify_untested_components` gain a keyword-only `scope_component_ids=None` (default = byte-identical FULL/ANALYSIS_ONLY). The orchestrator resolves the scope after `ANALYZING_SOURCE`, threads it into change-impact + test-discovery, and emits one `incremental.v1` Evidence row naming the changed modules. `run_change_safety` is deliberately **not** scoped (pure-DB, cheap, and its per-snapshot cache is cloned by later FULL runs). |
| **`webhook_deliveries`** | New table (`provider`+`delivery_id` unique) recording every delivery — handled or ignored — with `head_sha`/`before_sha`/`ref`/`changed_paths`/`changed_component_ids`/`run_id`/`status` (`received`\|`queued`\|`coalesced`\|`ignored_event`\|`ignored_no_repo`\|`ignored_no_change`). `AnalysisRun` gains `trigger` (JSON, `{"source":"webhook",…}` or `None`) and `changed_paths` (JSON list). Migration `0013_webhooks` creates the table and rebuilds `analysis_runs` from the model schema (`batch_alter_table(copy_from=…, recreate="always")` — drops the stale 3-value CHECK, adds the two columns; the four column-indexes are dropped/recreated explicitly around the rebuild since batch does not re-emit them). |
| **`POST /webhooks/github`** | `api/routers/webhooks.py` (async — needs raw bytes for HMAC). HMAC-SHA256 `X-Hub-Signature-256` verified with `hmac.compare_digest` against `github_webhook_secret` (missing secret / missing / malformed / bad sig → **401** `UNAUTHORIZED`, new `ErrorCode`). `X-GitHub-Delivery` replay → **409** `CONFLICT`. Non-`push` → 202 `ignored`. Repo resolved via `provider_for`/`parse` against registered `Repository` rows — **never auto-created** (unknown → 202 `ignored_no_repo`). Branch delete / no changed files → 202 `ignored_no_change`. Otherwise `create_run_with_job(mode=INCREMENTAL, requested_ref=after, config_hash=sha256("INCREMENTAL|<after>")[:32], idempotency_key="gh:<delivery>", trigger=…, changed_paths=…)` → 202 `{status:"queued", run_id}` + `Location`. A same-commit push already in flight → 202 `coalesced`. Registered in `app.py`. |
| **`create_run_with_job`** | Two new keyword params `trigger` / `changed_paths` passed straight to the `AnalysisRun` constructor; dedupe unchanged. |
| **Frontend badge** | `RunOut.trigger` (backend) → `serialize.run_out` → `api.ts` `interface Run.trigger`. `RunRoute.tsx` renders `<span className="pill trigger">triggered by push <sha7></span>` in the status row when `trigger.source === "webhook"`. `.pill.trigger` token in `styles.css`. Fixture gains `trigger: null` + a `runTriggeredByPush` factory. |

## Key design decisions

**INCREMENTAL is targeted, not just fewer stages.** A push creates a new commit = new
`RepositorySnapshot`, so nothing clones from a prior run — a pure stage-subset would
re-analyse every component in the stages it runs. So the change-impact rows and the
test-gap candidate list are computed **only for the changed components** via an optional
`scope_component_ids` kwarg that defaults to `None` (FULL / ANALYSIS_ONLY untouched).

**INCREMENTAL is sandbox-free (ends at `ANALYZING_TESTS`).** The roadmap prose lists
"… → failure detection", but `DETECTING_FAILURES` reads the `EXECUTING` junit artifact and
needs Docker. `ANALYSIS_ONLY` was deliberately cut at exactly this boundary in Phase 14;
INCREMENTAL follows suit so a push gets fast, Docker-free turnaround.

**`EnumString(RunMode)`, not a recurring CHECK migration.** `RunMode` has grown every few
phases; `Dependency.kind` already established the "plain VARCHAR for enums that grow"
pattern (`models.py`). One `analysis_runs` rebuild now (0013), none ever again.
`RunState`/`Stage`/`JobState` stay on `_enum` — closed lifecycle sets.

**Claude Evidence via a drain ring, not a provider signature change.** Passing `session`/
`run` into `_generate` would break the "AI only interprets, never persists" contract and
touch all five call sites + the mock. The ring keeps the provider pure and the mock path
byte-identical.

## Verification

| Check | Result |
|---|---|
| `pytest -q` (no Docker, no key) | green — `test_claude_provider.py` skips (no key), Docker tests skip; new webhook / incremental / EnumString / claude-unit tests pass |
| `pytest tests/unit/test_schema_drift.py` | green — `analysis_runs` rebuild + `webhook_deliveries` match `Base.metadata`; the `mode` retype is `modify_type`, filtered by `_STRUCTURAL` |
| migration round-trip | `db-upgrade` on a fresh SQLite → `alembic downgrade -1` → `upgrade head` clean; `analysis_runs` has no `mode` CHECK, keeps its four indexes + FKs |
| `pytest tests/integration/test_webhooks_api.py` | green — signed push → 202 queued INCREMENTAL run with a webhook `trigger`; bad sig → 401; replay → 409; non-push / unknown repo / no-change → 202 ignored; worker drives it to `ANALYZING_TESTS` with an `incremental.v1` Evidence row and no `claude:` `produced_by` |
| `pytest tests/integration/test_incremental_pipeline.py` | green — INCREMENTAL completes sandbox-free at `ANALYZING_TESTS`; `ChangeImpact` computed only for the changed module(s); a second push for a different sha is not dedupe-blocked |
| `ruff check archon tests alembic` | clean |
| gated live test | `ANTHROPIC_API_KEY=… pytest tests/integration/test_claude_provider.py` (with `backend[claude]`) → schema-valid `AssumptionAnalysis` whose surviving evidence refs all resolve |

## Known limitations / deferred

* **INCREMENTAL change-safety runs with degraded signals.** Skipping `ARCHAEOLOGIZING` +
  the scoring engines means the caller-at-risk signal (`LegacyDNA`/`Hotspot` rows) and the
  hidden-assumption count are absent; `run_change_safety` degrades to "not at risk" /
  count 0 rather than failing. Acceptable for a fast push check; a future `INCREMENTAL_FULL`
  could keep those stages.
* **No failure detection on the changed subset** — that needs `EXECUTING` (Docker); deferred.
* **`patch_proposal` stays division-scoped.** The Claude driver produces real output for the
  operations *as their call sites invoke them*; `healing/generation.py` only calls
  `patch_proposal` when `_find_divisor` succeeds, so broadening the patch context is future
  work, not part of the P19 "real driver" scope.
* **Prompt tuning** — the per-op prompts mirror the mock's documented behaviour; empirical
  tuning against real repos is follow-up.
* **AI cost/latency metric** — the `AICallRecord` fields (tokens, latency) land in Evidence
  `detail`; a Prometheus counter is a Phase 20 (observability) item.
