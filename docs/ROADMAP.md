# ARCHON Roadmap — Phases 13–20 (Hardening & Completion)

The 12 phases of `ARCHON_IMPLEMENTATION_PLAN` are all implemented; the closed loop runs
end to end. A read-only engineering review scored the codebase **7.5 / 10**. Phases 13–20
close every gap the review found, finish the remaining spec items (Excel §49–50, webhook
§51, real AI driver §13–14, multi-language §16–17, observability §55) and take the platform
to production quality — target **9.6 / 10**.

| Dimension | now | after 13–20 | driven by |
|---|---|---|---|
| Honesty / "no fakes" | 9.5 | 9.5 | — |
| Security | 9 | 9.6 | P15 redaction · P19 rate-limit/audit · P20 concurrency containment |
| Error handling / typing | 8.5 | 9.2 | P15 |
| Architecture | 8.5 | 9.4 | P15 dispatch table + resume · P19 ops layer |
| Docs | 8 | 9.2 | per-phase records · this roadmap · ARCHITECTURE §20+ |
| Code craft | 8 | 9.2 | P15 de-duplication |
| Scoring engines | 7 | 9 | P16 real data + calibration basis |
| **Frontend** | 8 | **9.2** | P17 componentise/route/design-system · P18 tests/a11y/viz |
| **Testing** | 6.5 | **9.2** | P14 backend · P18 frontend · P20 perf/load tier |
| Completeness vs spec | 6.5 | 9.6 | P13 Excel · P19 webhook + real AI · P20 multi-lang/scale |
| Operability | (unrated) | 9 | P19 metrics/deploy · P20 caching/concurrency under load |
| **Weighted** | **7.5** | **≈ 9.6** | |

Each phase keeps the §62 workflow and the completion gate: unit + integration + acceptance
tests green (or cleanly skipping), wired into pipeline / API / CLI / frontend as applicable,
no stub/TODO left representing complete work, a `docs/PHASE_N_COMPLETION.md` record, and a
new `## N.` section in `docs/architecture/ARCHITECTURE.md`.

---

## Phase 13 — Reporting & bulk I/O (§49–50)

**The last unbuilt named deliverable.** A `reporting/` package producing
`ARCHON_Legacy_Analysis.xlsx` (14 sheets) plus `repositories.xlsx` bulk input.

- **`archon/reporting/queries.py`** — the shared read layer the spec demands ("sourced from
  the same service/domain layer as the API, no separate engine"). One function per resource
  (`legacy_dna(session, run_id) -> list[LegacyDnaOut]`, …, ~19 total) holding the `select` +
  `*Out` mapper currently inlined in each router; the single copy of `_run_with_snapshot` /
  `_qn_map`. The Phase-5+ routers are refactored to delegate to it (folds in the router
  de-dup the review flagged).
- **`archon/reporting/workbook.py`** — `build_report(session, run_id) -> openpyxl.Workbook`;
  one `_sheet_<name>` per spec sheet (Executive Summary, Repository Understanding,
  Architecture, Legacy DNA, Change Safety, Change Impact, Technical Debt, Test Gaps,
  Characterization, Failures, Repairs, Modernization, Software Archaeology, Incident Memory),
  each calling `queries.*`; every AI-derived sheet carries confidence / classification /
  evidence columns.
- **`archon/reporting/bulk_import.py`** — `import_repositories_xlsx(session, src)`; per row
  (`Repository URL`, `Branch`, `Analysis Mode`, `Priority`) reuses `provider_for` +
  `RepositoryProvider.parse` (validation) + `JobManager.create_run_with_job(priority=…)` (the
  `priority` kwarg already exists). No new enqueue path.
- **`core/artifacts.py`** — `write_bytes` (copy of `write_text`). **`api/routers/reporting.py`** —
  `GET /runs/{id}/report.xlsx` (first binary endpoint; `Response` + `Content-Disposition`);
  optional `POST /repositories/bulk`. **CLI** — `archon report <run_id> [--out]`,
  `archon bulk-import <xlsx>`. **Frontend** — `api.downloadReport(runId)` blob helper + a
  "Download report (.xlsx)" button in `RunView`. **Deps** — `openpyxl>=3.1` (core).
- **Acceptance**: `GET /runs/{id}/report.xlsx` opens as a 14-sheet workbook whose cell values
  equal the matching JSON endpoints; a mixed 3-row `repositories.xlsx` creates the right repos
  + queued jobs with correct priority and reports the bad row.

## Phase 14 — Backend test & CI hardening

**Every backend test passes or skips cleanly with *and* without Docker; the scoring engines
get property-based proofs; a named end-to-end test; a model↔migration drift guard.**

- **`RunMode` split** — `_STAGE_PLANS[ANALYSIS_ONLY]` genuinely stops before `EXECUTING`
  (analysis prefix through `ANALYZING_CHANGE_IMPACT`); `FULL` = the whole `STAGE_ORDER`.
  This makes the entire analysis pipeline Docker-free-testable and matches the enum's own
  intent. `terminal_stage(mode)` already takes a mode; the ~17 phase-2/3/4 acceptance +
  ~30 `*_pipeline` / analysis `*_api` integration tests switch to `ANALYSIS_ONLY` and become
  Docker-free.
- **Docker gate** — every remaining test that asserts a `FULL` run reaches `COMPLETED`
  (phase 5/6/7 `test_run_completes_*`, healing / incidents / execution / characterization
  API tests) gains the `sandbox_image_available` fixture param → skips, never fails.
- **`tests/acceptance/test_end_to_end.py`** (new, Docker-gated) — one test driving
  `build_test_repo` through a full `FULL` run, asserting real rows at every stage boundary
  (snapshot SHA → components/deps → git → architecture roles → legacy-DNA/hotspot/change-
  safety → planted test gap → planted `ZeroDivisionError` → investigation names the root
  cause → ranked minimal patch `VERIFIED` + regression pass → `Incident` → `Modernization`
  plan → `report.xlsx` opens with 14 sheets).
- **`tests/unit/test_schema_drift.py`** (new) — `migrate.upgrade()` then
  `alembic.autogenerate.compare_metadata(ctx, Base.metadata)` == `[]` (small allowlist for
  SQLite's lossy bool/enum reflection). Catches a model/table added without a migration
  `_TABLES` entry.
- **`tests/unit/test_scoring_properties.py`** (new) — add `hypothesis` to `[dev]`. For
  `legacy_risk` / `hotspot` / `change_safety` / `understanding`: monotonic in each
  risk-increasing signal (§7 exceptions asserted the other way); score ∈ [0, 100];
  confidence ∈ [0, 1]; `explain()` contributions always reconstitute the score; threshold
  boundary flips (24.9 vs 25.0).
- **CI** — a `make ci` target (`ruff` + `pytest` + `npm run typecheck && npm run test`);
  `pytest-cov` fail-under gate (≥ 85 % on `archon/`); a GitHub Actions workflow with a
  no-Docker job and a Docker job.
- **Acceptance**: `pytest -q` with no Docker → **0 failures**, N skips; with the sandbox
  image → full green; `pytest tests/unit/test_scoring_properties.py` → hundreds of generated
  cases pass; coverage gate holds.

## Phase 15 — Core hardening & de-duplication

**Kill the mechanical duplication the review flagged; close the small correctness/robustness
seams.**

- **`analysis/scoring/_base.py`** — the single `_norm`, `ScoreResult` + `explain()`,
  `weighted_score(normalized, weights)`; `legacy_risk` / `hotspot` / `change_safety` import
  it. **`analysis/scoring/_reuse.py`** — the duplicated `_prior_run_id` / `_clone_from_prior`
  / `_write_artifact` blocks.
- **`pipeline/orchestrator.py`** — a `dict[Stage, _StageSpec]` dispatch table for the ~12
  pure analysis wrappers + the 22-field summary list (→ populate `PipelineResult` by
  `result_field`); the ~10 stateful stages stay explicit. Terminal
  `else: raise ArchonError(INTERNAL, …)`. **Resume-from-checkpoint**: `run()` re-enters at
  `next_stage(run.last_completed_stage)` instead of always `plan[0]` (closes the "docstring
  claims resumption" finding). Target ≤ ~450 lines.
- **`comparison/differ.py`** — one `_diff_by_qn(...)` for the five `_xxx_by_qn` sections;
  **`domain/enums.py`** — `enum_value(x) -> str` replacing the three `_cat()` copies.
  **`modernization/planner.py`** — `comp_by_id` dict replacing the O(n·m) scan.
- **`core/logging.py`** — redaction patterns for `sk-ant-…`, `Bearer …`, `AKIA…`, generic
  32+-char secrets under `authorization`; unit test with each shape in a message and in
  `extra_fields`.
- **`domain/ai_schemas.py` / `api/schemas.py`** — `Field(ge=0.0, le=1.0)` on float
  `confidence` DTO fields.
- **Docstring sweep** — remove/refresh every "wired up in a later phase" / "NOT YET REAL
  DATA" comment that later phases invalidated.
- **Acceptance**: full suite green with identical scoring numbers (unit tests pin them);
  orchestrator ≤ 450 lines; a deliberately-corrupted resume (kill mid-run, re-tick) finishes
  from the checkpoint.

## Phase 16 — Scoring calibration & real-data feedback

**The scoring framework is already versioned/explainable; give the constants a documented
basis and feed the engines real coverage + failure data.**

- **Real coverage → `legacy_risk.v2` / `hotspot.v2` / `change_safety.v2`.** The parser
  already exists (`testing/coverage.py::parse_coverage_xml` + `component_coverage_pct`) but
  is firewalled off by a documented Phase-8 scope cut. `BUILDING_LEGACY_DNA` runs before
  `EXECUTING`, so: read the **most recent prior completed run's** `coverage.xml` artifact for
  the same snapshot (via `Execution.coverage_ref`), resolve per component, set
  `coverage_is_proxy=False`; proxy (still flagged) only when no prior coverage exists.
  Bump the three `*_VERSION`s; register in `core/versions.py`. Update the ~4 Phase-5/6
  acceptance tests that pin the literal `0.5` proxy to assert `coverage_is_proxy` semantics.
- **Real `failure_count` → `legacy_risk` / `hotspot`.** Derive per component from
  `Failure.parsed_frames[].component_id` ∪ `Investigation.affected_component_ids` across the
  repo's run history; add as a small-weight real signal (still omitted, not zeroed, when the
  run had no `EXECUTING`).
- **Real `understanding` weights → `understanding.v2`.** Replace the all-`1.0`
  `UNDERSTANDING_DIMENSION_WEIGHTS` with a justified non-uniform set (architecture / behavior
  / testing above configuration) + rationale.
- **Calibration basis + `tests/acceptance/test_scoring_calibration.py`** (new) — a
  `thresholds.py` header documenting each `*_SCALE` against the fixture distributions; the
  test runs scoring over `build_scoring_repo` + `build_test_repo` and asserts each planted
  component lands in its intended bucket (`pricing_engine` → HIGH/CRITICAL legacy risk +
  RISKY/DANGEROUS change safety; `tax_rules` → LOW/SAFE).
- Migration `0013_scoring_v2` only if a column is added (likely none).
- **Acceptance**: second run of a repo shows `coverage_is_proxy=False` with real percentages;
  `test_scoring_calibration.py` green; property tests (P14) still hold at `.v2`.

## Phase 17 — Frontend architecture

**From one flat 2 300-line `App.tsx` to a componentised, routed SPA with a design system.**

- **Structure** — split into `src/lib/` (api client, hooks: `useRun`, `usePoll`, `useAsync`),
  `src/components/` (Pill, Card, DataTable, DeltaCell, ErrorBanner, LoadingSkeleton,
  EvidenceTag, ProgressBar), `src/panels/` (one file per analysis panel), `src/routes/`
  (`RepositoriesRoute`, `RunRoute`, `CompareRoute`). Add `react-router-dom` — real routes
  (`/`, `/runs/:id`, `/runs/:id/compare`), deep-linkable, back/forward works.
- **Design system** — a CSS-token layer (`tokens.css`: colour / space / type scale), light +
  dark, responsive (run view collapses to one column under 900 px); the existing colour maps
  become token references.
- **State** — one `usePoll` hook driving run-status polling with proper cleanup and backoff;
  a shared `useAsync` replacing the ~20 hand-rolled `useEffect(() => { let live … })` blocks
  and their silent `catch(() => undefined)`.
- **Acceptance**: `npm run typecheck && npm run build` green; no component over ~150 lines;
  every route deep-links and survives refresh; no data path bypasses the API; visual parity
  with today (screenshot diff acceptable).

## Phase 18 — Frontend testing, accessibility & visualization

**Give the frontend a real test suite and bring it to an a11y + UX bar that matches the
backend's rigor.**

- **Tests** — `vitest` + `@testing-library/react` + a hand-mocked `api` (or `msw`): a
  render test per panel (loading → rows → empty → error), the poller stops on terminal
  state, the comparison flow, the report download, a route smoke test, the design-token
  contrast check. `npm run test` + `--coverage` (≥ 80 % of `src/`), wired into `make ci`
  (P14). This is the biggest single lever on the **Testing → 9** score.
- **UX polish** — every panel: loading skeleton, typed error banner, empty state; a
  run-status progress bar with stage labels and a live evidence feed; the report-download
  button with progress; "triggered by push `<sha>`" badge (feeds P19).
- **Accessibility** — semantic landmarks, `aria-label`s, keyboard nav for the run/compare
  pickers and tables, visible focus rings, `prefers-reduced-motion`, WCAG-AA contrast on all
  tokens. A `vitest-axe` assertion on each route.
- **Visualization** — upgrade the inline SVG module graph to a real force/hierarchy layout
  with zoom/pan and role colouring; a small sparkline component reused by Git Evolution,
  Hotspots, and the report progress.
- **Acceptance**: `npm run test` green with coverage gate; `vitest-axe` clean on every
  route; Lighthouse a11y ≥ 95 on the run view.

## Phase 19 — Real `ClaudeAIProvider` + GitHub webhook (§13–14, §51)

**Make "AI Software Archaeologist" literally true, and add push-triggered incremental
analysis — two remaining spec items.**

- **`providers/ai/claude.py`** — the real driver behind the existing `AIProvider` ABC.
  Per-op prompt templates (root cause, patch proposal, test generation, behavior, historical
  intent, assumption analysis, modernization); Anthropic Messages API via the SDK with tool /
  JSON-schema-enforced structured output; **the same `schema → evidence → domain` validation
  pipeline** in `base.py` runs unchanged on its output (unresolvable evidence dropped,
  confidence floored). `ARCHON_AI_PROVIDER=claude` wired in `get_ai_provider()`; **the mock
  stays the default** and the only provider the test suite and offline dev use. A live,
  `ANTHROPIC_API_KEY`-gated integration test (skips like the Docker tests). Token-budget +
  retry + timeout handling; every call logged as `Evidence` with `produced_by="claude:<model>"`.
- **`api/routers/webhooks.py`** — `POST /webhooks/github`: HMAC-SHA256 `X-Hub-Signature-256`
  validation against `ARCHON_GITHUB_WEBHOOK_SECRET`, `X-GitHub-Delivery` dedupe (a
  `webhook_deliveries` table + migration), `push` events only. Resolve changed files →
  changed `Component`s → enqueue a **targeted** run (new `RunMode.INCREMENTAL` /
  `_STAGE_PLANS` entry: ingest → snapshot → source → graph → change-impact → change-safety →
  targeted test discovery/gap → failure detection) reusing the existing engines rather than a
  full re-analysis. Frontend: the "triggered by push `<sha>`" badge from P18 lights up.
- **Acceptance**: with a key, a real Claude run produces schema-valid, evidence-checked
  conclusions for the fixture bug and the loop still reaches a `VERIFIED` patch; without a
  key everything runs on the mock unchanged. A signed webhook payload for a 1-file change
  enqueues a run whose plan is the targeted subset; an unsigned / replayed payload → 401 /
  409.

## Phase 20 — Observability, scale & operability (§16, §18, §53, §55)

**The production-readiness capstone: prove it holds up, and make it operable.**

- **Observability (§55)** — OpenTelemetry traces + Prometheus metrics (`/metrics`): per-stage
  duration histograms, queue depth, sandbox-container gauge, AI-call count/latency/cost,
  run-outcome counters. A `runs` operational view (run / repo / snapshot / commit / mode /
  current-stage / status / start / end / duration / errors / AI activity) exposed via
  `GET /admin/runs` and a small frontend Ops screen. Structured audit log of every state
  transition.
- **Deployment (§18)** — hardened `docker/docker-compose.prod.yml` (non-root images,
  healthchecks, resource limits, `restart: unless-stopped`, secrets via env-file not
  baked); readiness/liveness probes; migration-on-start guard with advisory lock; graceful
  worker shutdown (finish current stage, requeue nothing half-done); connection pooling +
  `pool_pre_ping`.
- **Multi-language / support contract (§16–17)** — make `PARTIALLY_SUPPORTED` real: a
  mixed-language repo analyses its Python and *summarises* the rest (file counts, languages,
  a `NON_PYTHON_SUMMARY` evidence row) instead of silently ignoring it; shallow/absent
  history degrades archaeology with a recorded warning; every hard-limit breach returns a
  structured reason and every soft-limit breach degrades-and-records (spec §16).
- **Performance & caching (§53)** — a `tests/perf/` tier: snapshot/AST/graph reuse proven
  across runs (cache-key correctness — never reused across incompatible engine versions or
  snapshots), a large synthetic repo within limits completes under `max_analysis_duration`,
  N concurrent runs respect the running-job cap + sandbox semaphore with **zero orphaned
  containers** (reaper verified), `SELECT … FOR UPDATE SKIP LOCKED` contention test on
  Postgres.
- **Rate limiting & abuse** — per-IP limit on `POST /repositories/runs` and the webhook;
  request-size caps; the existing `RepositoryLimits` enforced end-to-end with tests.
- **Acceptance**: `/metrics` scrapes cleanly; `docker compose -f docker-compose.prod.yml up`
  passes healthchecks; a mixed-language fixture yields a Python analysis + a non-Python
  summary and `support_level == PARTIALLY_SUPPORTED`; the perf tier's concurrency test leaves
  no containers; killing the worker mid-run and restarting resumes to `COMPLETED`.

---

## Sequencing

13 → 14 → 15 → 16 → 17 → 18 → 19 → 20.

- **13** is additive (low risk); it also lands the shared read layer that 20's Ops views reuse.
- **14**'s `RunMode` split unblocks Docker-free testing for everything after and is a
  prerequisite for 15's resume work and 16's re-run scenarios.
- **15** is a pure refactor (scoring numbers pinned by unit tests) — do it before 16, which
  deliberately *changes* those numbers.
- **16** has the most existing-test churn (pinned proxy-coverage scores) — isolated after the
  de-dup so failures are unambiguous.
- **17 → 18** are the frontend arc; 18's test suite is the main driver of Testing → 9.
- **19** (real AI + webhook) and **20** (ops + scale) are the two "make it a product" phases
  and are independent of each other — 20 can start while 19's Claude driver is in review.
