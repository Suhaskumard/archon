# Phase 2 — Source Intelligence — Completion Record

Per spec §62 step 11 and the plan's per-phase completion gate. Builds on Phase 1.

## Scope delivered

The `ANALYZING_SOURCE` stage: deterministic Python-`ast` extraction of a checkout into
`components` + `dependencies`, wired into the pipeline for `ANALYSIS_ONLY` / `FULL` runs.

```
… SNAPSHOTTING ─▶ ANALYZING_SOURCE
     walk checkout ─▶ per-module ast parse ─▶ raw import/inherit/call records
     ─▶ cross-module resolution ─▶ Component + Dependency + Evidence rows
     (cached on the snapshot: a second run over the same commit does not re-parse)
```

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Extractor | `archon/analysis/source/extractor.py` | two-pass walk; FILE/MODULE/CLASS/FUNCTION/METHOD; nested funcs to depth 3; `src/` layout; syntax-error tolerant |
| Complexity | `archon/analysis/source/complexity.py` | `complexity.v1` — explicit, documented, versioned McCabe-style model |
| Resolution | `archon/analysis/source/resolve.py` | conservative import/inherit/call resolution against the snapshot component index; relative imports; `self.method()`; constructor calls |
| Entry points | `archon/analysis/source/entrypoints.py` | `__main__` guards, console_scripts (pyproject / setup.cfg / setup.py), framework signals |
| Classification | `archon/analysis/source/classify.py` | test-file and config-file detection |
| Persistence | `archon/analysis/source/persist.py` | parent-before-child insert, dedupe, CONTAINS backbone, evidence, per-snapshot caching |
| Schema | `alembic/versions/0002_source_intelligence.py` | `components`, `dependencies` tables |
| Pipeline | `archon/pipeline/orchestrator.py` | `_STAGE_PLANS` per `RunMode`; `_source` stage; keeps the checkout for the stage |
| API | `archon/api/routers/source.py` | components / component detail / dependencies / run source-summary; filtering + pagination |
| Frontend | `frontend/src/App.tsx` | "Source Intelligence" panel on a completed run — component/edge counts, entry points, most-complex table |

## Tests — `cd backend && pytest`

**112 passed** (was 63; +49 for Phase 2). Coverage 89 % of `archon/`.

| Tier | Files | Covers |
|---|---|---|
| unit | `test_complexity` (11 cases + nesting + module level), `test_source_classify`, `test_source_extractor` | exact complexity numbers; test/config path rules; component inventory, resolved IMPORTS/INHERITS/CALLS/`self.`/constructor edges, metrics & flags, console-script + `__main__` detection, syntax-error tolerance |
| integration | `test_source_pipeline`, `test_source_api` | full `ANALYSIS_ONLY` run → DB rows; `billing→calculator` import, `RushOrder→Order` inherit, CONTAINS backbone, `unit_price` cx=2; **per-snapshot caching** (no duplicate rows on re-run); `INGEST_ONLY` skips the stage; every API endpoint incl. filters + 404s |
| acceptance | `test_phase2_source_intelligence` | exact fixture inventory (FILE 10 / MODULE 8 / CLASS 2 / FUNCTION 8 / METHOD 4); key resolved relationships; `divide` cx=1, `unit_price` cx=2 args=`[total,qty]`, `reserve` raises `ValueError`; classified `source.v1` evidence; engine-version pinning; cached re-run |

The fixture repo (`tests/fixtures/build_test_repo.py`) gained `legacy_shop/orders.py` in its
2nd commit (an `Order` class + `RushOrder(Order)` subclass) so classes, methods, `super()`
and inheritance are exercised — commit count stays 3, so Phase 1 assertions are unchanged.

## Verified manually

* `archon analyze ./legacy-shop --mode analysis_only --wait` → `COMPLETED`, evidence:
  "Extracted 8 Python modules (2 classes, 8 functions, 4 methods)", "Dependency edges: 13
  total, 13 resolved".
* `alembic upgrade head` applies `0001 → 0002` cleanly on SQLite; `components` has the
  promoted `is_test`/`is_entrypoint`/`is_config` columns.
* `ruff check archon tests alembic` → clean. `frontend: npm run build` → clean.

## Known limitations / deferred

* Call resolution is intra-snapshot and conservative — dynamic dispatch, `getattr`, and
  calls on locally-typed variables are not resolved (they are simply omitted, not guessed).
* One CONTAINS edge per component: fine for the fixture; for very large repos this is the
  biggest row source in `dependencies` (bounded by component count).
* `role` on `Component` is null until Phase 3 (architecture reconstruction), which also
  builds the NetworkX graph and adds `GET /runs/{id}/architecture`.
