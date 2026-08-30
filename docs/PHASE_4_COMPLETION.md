# Phase 4 — Software Archaeology — Completion Record

Per spec §62 step 11 and the plan's per-phase completion gate. Builds on Phases 1–3.
Introduces the project's first AI step behind a mock provider.

## Scope delivered

Two new pipeline stages for `ANALYSIS_ONLY` / `FULL` runs, plus the shared `AIProvider`
abstraction used by every later phase.

```
… ANALYZING_SOURCE
   ─▶ ANALYZING_GIT        commits, churn/age/co-change, CHANGED_WITH / CHANGED_BY edges
   … BUILDING_GRAPH … RECONSTRUCTING_ARCHITECTURE
   ─▶ ARCHAEOLOGIZING      deterministic behaviour facts + hidden-assumption heuristics,
                           then MockAIProvider interprets intent / behaviour / risk
```

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Git history | `archon/analysis/git/history.py` | `git log --numstat` parse via `gitcli.run_git`; control-byte record framing; rename/binary/merge handling; bounded by `max_git_history_commits` |
| Git metrics | `archon/analysis/git/metrics.py` | churn, commit_count, first/last seen, `age_days`, distinct authors; co-change over `.py` pairs (skips `__init__.py` + bulk commits); `confidence = count / min(commit_count)` |
| Git persist | `archon/analysis/git/persist.py` | `commits` rows, `Component.metrics["git"]`, `CHANGED_WITH` (module↔module) + `CHANGED_BY` (component→sha) edges; snapshot-cached |
| AI schemas | `archon/domain/ai_schemas.py` | `AIEnvelope` + `HistoricalIntent` / `BehaviorAnalysis` / `AssumptionAnalysis`, versioned |
| AI provider | `archon/providers/ai/` | `AIProvider` ABC + validation pipeline (schema → evidence-ref check → confidence floor), `MockAIProvider` (deterministic, offline), `get_ai_provider()` |
| Assumptions | `archon/analysis/archaeology/assumptions.py` | 8 conservative AST heuristics (division, global_state, dict_key, environment, timezone, empty_collection, null, …) that fire on a clear instance and stay quiet when guarded |
| Behaviour | `archon/analysis/archaeology/behavior.py` | deterministic inputs/outputs/side-effects/exceptions/callers/callees/tests/invariants from AST + graph + git |
| Archaeology runner | `archon/analysis/archaeology/reconstruct.py` | per-assumption + per-component AI calls, persists `assumptions` + `behavior_reconstructions`, writes the `archaeology` artifact, snapshot-cached by row-copy |
| Schema | `alembic/versions/0004_archaeology.py` | `commits`, `assumptions`, `behavior_reconstructions` |
| Pipeline | `archon/pipeline/orchestrator.py` | `_ANALYSIS_STAGES` gains `ANALYZING_GIT` + `ARCHAEOLOGIZING`; `_git` / `_archaeology` methods; `ai_provider` pinned into `engine_versions` |
| API | `archon/api/routers/archaeology.py` | `/runs/{id}/evolution`, `/snapshots/{id}/commits`, `/components/{id}/history`, `/runs/{id}/behavior`, `/components/{id}/behavior`, `/runs/{id}/assumptions` |
| Frontend | `frontend/src/App.tsx`, `api.ts` | Git Evolution (timeline sparkline + churn table + co-change), Software Archaeology / Why Does This Exist (per-component purpose, history, callers, invariants, test-gap flag), Hidden Assumptions table (risk pill + suggested test) |
| Tests helper | `tests/conftest.py` | `terminal_stage(mode)` — tests read the pipeline's last stage instead of pinning a literal, so future phases don't ripple |

## Tests — `cd backend && pytest`

**185 passed** (was 149; +36 for Phase 4). `ruff check archon tests alembic` clean.

| Tier | Files | Covers |
|---|---|---|
| unit | `test_git_history` (numstat parse, rename/binary/merge, truncation), `test_git_metrics` (churn/age/co-change math, `__init__`/bulk/merge exclusion), `test_assumptions` (each heuristic fires + stays quiet when guarded; clean module = no findings), `test_mock_ai_provider` (deterministic, schema-valid, unresolved evidence dropped + confidence floored, risk weighting, malformed → `AIOutputError`) | 27 cases |
| integration | `test_git_pipeline` (3 commits, `metrics["git"]`, CHANGED_WITH module-only, CHANGED_BY→commits, caching), `test_archaeology_pipeline` (assumptions + behaviour rows, artifact, row-copy caching, INGEST_ONLY skip), `test_archaeology_api` (all 6 endpoints + filters + 404/409) | |
| acceptance | `test_phase4_archaeology` | `billing` commit_count 2 / `calculator` 1 / `inventory` 1; `billing`/`calculator` older than `inventory`; `billing↔calculator` CHANGED_WITH; ≥3 assumptions incl. `division` in calculator.divide and `global_state` `_STOCK` in inventory (elevated to HIGH — untested); `reserve` behaviour lists `ValueError`, `tests == []` (the known gap), calls `line_total`; classified `git.v1`/`archaeology.v1`/`assumptions.v1` evidence; `engine_versions["ai_provider"] == "mock"` |

The fixture was **backdated** (commits at 2026-06-01 / 07-01 / 08-01) so churn / age /
co-change carry real signal; file/module/function counts are unchanged, so Phase 2/3
acceptance is unaffected.

## Verified manually

* `archon analyze ./shop --mode full --wait` → `COMPLETED` at `ARCHAEOLOGIZING`; evidence
  "Analyzed 3 commit(s) over 61 day(s) (1 author(s)); 12 co-change edge(s)" and
  "Reconstructed behaviour for 20 component(s); 4 hidden assumption(s) (3 high-risk)";
  `<artifact_root>/<run_id>/archaeology.json` written.
* HTTP: `/runs/{id}/evolution` → monthly timeline + top churn + `billing↔calculator`
  co-change; `/runs/{id}/assumptions` → risk-sorted (division MEDIUM, `_STOCK` HIGH);
  `/runs/{id}/behavior?q=inventory.reserve` → purpose, `exceptions:["ValueError"]`,
  `tests:[]`.
* `alembic upgrade head` applies `0003 → 0004` cleanly on SQLite.
* `frontend: npm run build` clean.

## Known limitations / deferred

* `MockAIProvider` only rephrases deterministic findings; a real `ClaudeAIProvider` is a
  stub that raises. The validation pipeline (schema + evidence-ref + confidence floor) is
  fully exercised regardless.
* Assumption heuristics are intra-function and conservative — no cross-procedure dataflow;
  `ordering` / `schema` / `initialization` kinds are declared but lightly implemented.
* Behaviour "side effects" are inferred from call targets' roles + async/generator flags,
  not from a real effect analysis.
* `FAILED_IN` / `FIXED_BY` / `AFFECTS` edge kinds remain declared-only (Phase 9).
