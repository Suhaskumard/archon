# Phase 5 — Legacy DNA, Technical Debt, Hotspots, Understanding — Completion Record

Per the plan's Phase 5 scope (§27–30) and the per-phase completion gate. Builds on
Phases 1–4. Four deterministic scoring/detection engines — no AI step in this phase.

## Scope delivered

Four new pipeline stages for `ANALYSIS_ONLY` / `FULL` runs, consuming signals Phases 2–4
already computed.

```
… ARCHAEOLOGIZING
   ─▶ SCORING_UNDERSTANDING   evidence-coverage score across 6 dimensions
   ─▶ BUILDING_LEGACY_DNA     per-component Legacy Risk score + full signal breakdown
   ─▶ ANALYZING_TECH_DEBT     13 tech-debt detectors → TechnicalDebtFinding rows
   ─▶ SCORING_HOTSPOTS        per-component Hotspot score (signals-overlap bonus)
```

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Scoring math | `archon/analysis/scoring/legacy_risk.py`, `hotspot.py`, `understanding.py` | Pure functions, no DB. Weighted sums of normalized [0,1] signals; versioned via `thresholds.py`. `hotspot.v1` adds a multiplicative "signals overlap" bonus when ≥3 signals are independently elevated (§29). |
| Tech-debt detectors | `archon/analysis/scoring/tech_debt_detectors.py` | 13 categories. 6 are pure lookups against Phase 2-4 data (`long_functions`, `large_classes`, `circular_dependencies`, `high_coupling`, `dead_code_candidates`, `global_state_from_assumptions` — the last reuses Phase 4's `assumptions` table verbatim, zero new AST code). The remaining 7 (`duplicate_logic`, `low_cohesion`, `deprecated_apis`, `hardcoded_config`, `broad_except`, `silent_failure`, `magic_numbers`) run one AST pass per file (`detect_ast_debt`). |
| Legacy DNA runner | `archon/analysis/scoring/legacy_dna.py` | `run_legacy_risk` sources complexity/churn/coupling/coverage-proxy/assumption-count per component, computes a cheap 4-detector debt subset internally (see Known limitations), persists `LegacyDNA` + a mirrored `RiskAssessment` row, writes the `legacy_dna` artifact. Snapshot-cached. |
| Tech-debt runner | `archon/analysis/scoring/tech_debt.py` | `run_tech_debt_detection` runs the full 13-detector pass, resolves AST findings to the nearest enclosing component by line range, persists `TechnicalDebtFinding` rows. Snapshot-cached. |
| Hotspot runner | `archon/analysis/scoring/hotspots.py` | `run_hotspot_scoring` reuses `LegacyDNA` rows (complexity/churn/coupling/coverage) plus the *full* persisted `TechnicalDebtFinding` set as its debt signal, since it runs last. Snapshot-cached. |
| Understanding runner | `archon/analysis/scoring/understanding_run.py` | `run_understanding` aggregates evidence coverage across 6 dimensions (architecture, dependency, behavior, historical, testing, configuration) from rows Phases 2-4 already wrote. Cheap — always recomputed, never cached. |
| Schema | `alembic/versions/0005_scoring.py` | `risk_assessments`, `legacy_dna`, `technical_debt_findings`, `hotspots` |
| Enums | `domain/enums.py` | `RiskCategory` (LOW/MODERATE/HIGH/CRITICAL), `HotspotClassification` (STABLE/WATCH/RISKY/CRITICAL), `TechDebtCategory` (13 values), `TechDebtSeverity` (LOW/MEDIUM/HIGH/CRITICAL) |
| Pipeline | `archon/pipeline/orchestrator.py` | `_ANALYSIS_STAGES` gains the 4 new stages; `_understanding`/`_legacy_dna`/`_tech_debt`/`_hotspots` methods; 4 new `PipelineResult` fields |
| API | `archon/api/routers/scoring.py` | `/runs/{id}/legacy-dna`, `/components/{id}/legacy-dna`, `/runs/{id}/hotspots`, `/runs/{id}/technical-debt`, `/runs/{id}/understanding` |
| Frontend | `frontend/src/App.tsx`, `api.ts` | Repository Understanding (dimension bars), Legacy DNA (risk-sorted table with a coverage-proxy footnote), Technical Debt (severity-sorted table), Hotspots (score-sorted table with elevated-signal reasons) |
| Fixture | `tests/fixtures/build_scoring_repo.py` | A second, independent fixture repo (`legacy_shop`/`build_test_repo.py` is untouched — Phase 4's acceptance test pins its exact commit/churn/age numbers). Plants a stable module (`tax_rules`), a risky module (`pricing_engine`: deep branching, no tests, high fan-in, forced import cycle, planted debt smells), and a documented-exception module (`shipping_calculator`: churny/complex but tested). |

## Tests — `cd backend && pytest`

All prior tests unchanged and green (`legacy_shop`/`build_test_repo.py` never touched).
`ruff check archon tests alembic` clean.

| Tier | Files | Covers |
|---|---|---|
| unit | `test_legacy_risk_scoring`, `test_hotspot_scoring` (overlap-bonus math), `test_repository_understanding`, `test_tech_debt_detection` (one hit + one non-hit per detector, all 13 categories) | pure-function level, no DB |
| integration | `test_scoring_pipeline` (row shapes, `RiskAssessment` mirrors `LegacyDNA`, cache-reuse on a second run, `engine_versions` keys present), `test_scoring_api` (all 5 endpoints, filters, 404/409) | |
| acceptance | `test_phase5_scoring` | `pricing_engine.legacy_risk_score` > `tax_rules`'s (HIGH/CRITICAL vs LOW/MODERATE), same ordering on Hotspot classification; `shipping_calculator` (documented coverage-proxy exception) scores strictly between the two, with the coverage contribution visible and bounded in `factor_breakdown`; a richer-evidence run scores higher **and** more confident Repository Understanding than a minimal one-file/one-commit repo built inline in the test |

## Verified manually

* `archon analyze <repo> --mode full --wait` reaches `COMPLETED` at `SCORING_HOTSPOTS`;
  `engine_versions` carries `legacy_risk`/`hotspot`/`understanding`/`tech_debt`;
  `<artifact_root>/<run_id>/{understanding,legacy_dna,tech_debt,hotspots}.json` written.
* HTTP: all 5 new endpoints return correctly shaped, filterable, sorted data against a
  live `FULL` run of the scoring fixture.
* Frontend: `npm run build` clean; all four new panels render real data end-to-end
  against a locally completed run (Repository Understanding's dimension bars, Legacy
  DNA's risk-sorted table with coverage-proxy footnote, Technical Debt's severity table,
  Hotspots' score-sorted table with elevated-signal reasons) — verified via a live
  backend + frontend dev server and a completed run on the scoring fixture.

## Known limitations / deferred

* **Coverage is a proxy, not real coverage data** (Phase 8 adds actual test execution).
  `LegacyDNA.coverage` is `0.5` if the owning module has a `TESTED_BY` edge, else `0.0`;
  every such value carries `coverage_is_proxy=True` and is always counted as a defaulted
  signal in the confidence calculation — never presented as measured coverage.
* **Historical failures are omitted, not defaulted** (Phase 9 adds `Failure`/`Execution`
  tables). The signal is excluded from both the weighted sum and the confidence
  denominator entirely, rather than silently scored as "zero risk."
* **Legacy Risk's `debt_score` uses a 4-detector subset** (long functions, large classes,
  circular dependencies, high coupling) computed inline, not the full 13-detector set —
  the fixed `Stage` order runs `BUILDING_LEGACY_DNA` before `ANALYZING_TECH_DEBT`, so the
  full set isn't available yet. `SCORING_HOTSPOTS` (which runs last) does consume the
  full 13-detector set. Documented as a deliberate, bounded scope decision.
* **Duplicate-logic detection is structural only** (Type-1/2: identical after blanking
  names/constants) — no semantic clone detection.
* **`RiskAssessment` is intentionally generic** (`engine_version`-keyed) so Change Safety
  (Phase 6) and Patch Ranking (later) can reuse it without a new table each time;
  `LegacyDNA` stays the Legacy-Risk-specific detail breakdown.
* Change Safety and Patch Ranking engines remain declared-only (`domain/enums.py`,
  `ARCHITECTURE.md` §12) — out of scope for Phase 5, implemented in Phases 6 and 9+.
