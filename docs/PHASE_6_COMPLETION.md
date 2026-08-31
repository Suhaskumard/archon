# Phase 6 — Change Safety & Change Impact — Completion Record

Per the plan's Phase 6 scope (§31–32) and the per-phase completion gate. Builds on
Phases 1–5. Two deterministic engines — no AI step in this phase, same as Phase 5.

## Scope delivered

Two new pipeline stages for `ANALYSIS_ONLY` / `FULL` runs, consuming signals Phases 2–5
already computed (including a new cross-engine read of Phase 5's own `LegacyDNA`/
`Hotspot` rows from the same run).

```
… SCORING_HOTSPOTS
   ─▶ ASSESSING_CHANGE_SAFETY  per-component safety score (higher = safer) + prep list
   ─▶ ANALYZING_CHANGE_IMPACT  dependents/callers/tests/co-changes per module
```

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Scoring math | `archon/analysis/scoring/change_safety.py` | Pure. Unlike Legacy Risk/Hotspot ("higher = riskier"), Change Safety is "higher = safer" — every negative-direction signal is inverted (`1 - normalized`) before weighting, so `explain()`'s contributions stay directly interpretable. |
| Change safety runner | `archon/analysis/scoring/change_safety_run.py` | `run_change_safety` sources coverage/complexity/coupling/centrality/assumptions/churn the same way `legacy_dna.py` does, plus a genuinely new cross-engine signal: **callers-at-risk**, read from this run's own already-persisted `LegacyDNA.category`/`Hotspot.classification`. Persists `ChangeAssessment` (not `RiskAssessment` — see Known limitations), writes the `change_safety` artifact. Snapshot-cached. |
| Change impact | `archon/analysis/scoring/change_impact.py` | Pure `direct_and_indirect_dependents(mg, node)` (predecessors / ancestors-minus-direct on `build_module_graph`'s reused-as-is graph) plus DB-touching orchestration: callers (`CALLS` edges), related tests (`TESTED_BY`), historical co-changes (`CHANGED_WITH`), external integrations (`external=True` edges), and a deterministic "what could break / which tests to run / what to do first" template. `run_change_impact` precomputes a `ChangeImpact` row for every MODULE; `compute_and_persist_change_impact` is the on-demand path shared with the API. |
| Schema | `alembic/versions/0006_change_safety.py` | `change_assessments`, `change_impacts` |
| Enum | `domain/enums.py` | `ChangeSafetyCategory` (SAFE/CAUTION/RISKY/DANGEROUS) |
| Pipeline | `archon/pipeline/orchestrator.py` | `_ANALYSIS_STAGES` gains `ASSESSING_CHANGE_SAFETY` + `ANALYZING_CHANGE_IMPACT`; `_change_safety`/`_change_impact` dispatch methods; 2 new `PipelineResult` fields |
| API | `archon/api/routers/scoring.py` (extended, no new router file) | `GET /runs/{id}/change-safety` (ascending by score — least-safe first), `POST /runs/{id}/change-impact` (`{"component_id"}` — returns the precomputed row if it exists, else computes-and-upserts on demand) |
| Frontend | `frontend/src/App.tsx`, `api.ts` | Change Safety (flat table, colored category pill, recommended-preparation list); Change Impact (component picker + "Compute impact" button + detail card, adapting `ArchaeologyPanel`'s picker/detail shape) |

## Tests — `cd backend && pytest`

All prior tests unchanged and green (`scoring_repo`/`build_scoring_repo.py` untouched —
its stable/risky/documented-exception module shapes already fit Phase 6's needs).
`ruff check archon tests alembic` clean.

| Tier | Files | Covers |
|---|---|---|
| unit | `test_change_safety_scoring.py` (full-safety → SAFE, full-risk → DANGEROUS, omitted-signal renormalization, and an explicit **sign-flip regression test**: lower raw complexity/coupling/centrality/caller-risk/churn → higher contribution), `test_change_impact.py` (pure `direct_and_indirect_dependents` against a hand-built diamond+chain graph: direct = predecessors, indirect = ancestors minus direct minus self, upstream nodes excluded) | pure-function level, no DB |
| integration | `test_change_safety_pipeline.py` (rows persisted, `ChangeImpact` precomputed for every MODULE, cache-clone on a second run produces byte-identical `factor_breakdown` including the caller-risk factor), `test_change_safety_api.py` (GET filters/404, POST for a precomputed MODULE returns instantly, POST for an uncomputed FUNCTION computes-and-upserts then a second POST returns the same row, 404/409 cases) | |
| acceptance | `test_phase6_change_safety.py` | `tax_rules.safety_score` > `pricing_engine`'s with differing categories (stable/tested vs. coupled/unstable/untested, spec §7/§31); `POST .../change-impact` for `pricing_engine` returns `checkout`/`invoice`/`promotions`/`discount_rules` among its dependents, matching the fixture's known import graph |

## Verified manually

* `archon analyze <repo> --mode full --wait` reaches `COMPLETED` at
  `ANALYZING_CHANGE_IMPACT`; `engine_versions` carries `change_safety`/`change_impact`;
  `ChangeAssessment` rows exist for every scored component, `ChangeImpact` rows for every
  MODULE.
* HTTP: both new endpoints return correctly shaped, filterable/sortable data against a
  live `FULL` run; the on-demand POST path verified for both a precomputed module and an
  uncomputed function (idempotent on repeat).
* Frontend: `npm run build` clean; both new panels verified rendering real data against
  a locally completed run — Change Safety's table (ascending safety score, colored
  category pills, recommended-preparation lists) and Change Impact's picker → POST →
  detail-card flow (direct/indirect dependents, callers, co-changes, and the three-part
  narrative), via a live backend + frontend dev server.
* **Fixed a pre-existing dev-proxy gap** discovered while verifying the Change Impact
  panel live: `frontend/vite.config.ts` never proxied `/snapshots` or `/components` to
  the backend, so `listComponents` silently received the SPA's own HTML (200 OK) instead
  of JSON in dev mode. Latent since Phase 2 (only ever lazily triggered, e.g.
  `SourceIntel`'s "load components" link); Change Impact's on-mount fetch was the first
  caller to surface it as a hard crash. Fixed by adding both prefixes to the proxy map.

## Known limitations / deferred

* **`ChangeAssessment` is a standalone table, not a `RiskAssessment` row.**
  `RiskAssessment.category` is a closed `_enum(RiskCategory)`
  (LOW/MODERATE/HIGH/CRITICAL) — incompatible with Change Safety's
  SAFE/CAUTION/RISKY/DANGEROUS vocabulary. Widening the column to a shared `EnumString`
  would let two incompatible vocabularies collide in one query; a lossy 4-to-4 mapping
  would cost real information for zero present benefit. `RiskAssessment`'s docstring is
  narrowed to note it's for the LOW/MODERATE/HIGH/CRITICAL family only — Change Safety
  gets its own table instead, exactly as the plan doc's own data model already specified.
* **Coverage remains the Phase 5 `TESTED_BY`-edge proxy** — no real coverage data exists
  until Phase 8. Same 0.5/0.0 proxy, same "always defaulted for confidence" treatment.
* **Historical change-success rate and historical failures are omitted, not defaulted**
  — no `PatchVerification`/`Incident`/`Failure` data exists until Phase 9+. Both are
  excluded from the signal set and the confidence denominator entirely.
* **`ChangeImpact` has no run-to-run caching** (deliberate simplification): it's cheap
  enough (pure graph/query reads, no AI) to always recompute per run, and the on-demand
  POST path only ever checks the *current* run's own rows — avoids a caching-correctness
  edge case around which components were added on-demand to a prior run.
* Patch Ranking remains declared-only (`domain/enums.py`, `ARCHITECTURE.md` §12) — out
  of scope for Phase 6, implemented in Phase 9+.
