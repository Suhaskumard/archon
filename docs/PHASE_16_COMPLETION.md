# Phase 16 — Scoring calibration & real-data feedback — Completion Record

Per `docs/ROADMAP.md` Phase 16. The scoring *framework* was already versioned and
explainable; this phase gives the constants a documented, test-pinned basis and feeds
the engines **measured coverage** and **real failure counts** instead of proxies.

## Scope delivered

| Change | Detail |
|---|---|
| `analysis/scoring/coverage_refine.py` (new) | `refine_scores_with_measured_coverage(...)` - runs at the end of `EXECUTING`, after test-gap analysis: recomputes each `LegacyDNA` + its `RiskAssessment` + `Hotspot` row from this run's measured per-component coverage (`testing/coverage.py::component_coverage_pct`), flips `coverage_is_proxy=False`, emits one `EXECUTING` `Evidence`. `backfill_failure_counts(session, run)` - runs one stage later from `DETECTING_FAILURES` (failures don't exist yet at `EXECUTING` time), fills `LegacyDNA.failure_count` from `Failure.parsed_frames[].component_id`. `coverage_refine.v1`. |
| `legacy_risk.py` → **v2** | `legacy_risk_score(signals, *, coverage_is_proxy=True)` - when `False`, `coverage_gap` is no longer a defaulted signal, so `confidence` rises. Runner passes the default (proxy); the refine pass passes `False`. |
| `change_safety.py` | gained the same `coverage_is_proxy=True` param (forward-looking); **stays v1** - its runner still scores with the proxy, so its row output is unchanged. Post-`EXECUTING` refinement of `ChangeAssessment` is deferred (its signal set - centrality / caller-risk / caller-count - isn't fully reconstructable from the row without more plumbing). |
| `understanding.py` → **v2** | `UNDERSTANDING_DIMENSION_WEIGHTS` is no longer all-`1.0`: architecture 1.5, behavior 1.3, testing 1.3, dependency 1.0, historical 0.8, configuration 0.6 - weighted toward the dimensions that most determine whether you can safely *change* the code. (`understanding.v2` was already bumped in Phase 15's doc-sweep prep; the weights land here.) |
| `thresholds.py` | new **Calibration basis** header documenting how each `*_SCALE` was chosen against the fixture distributions (e.g. `COMPLEXITY_SCALE=15` ≈ `pricing_engine.price_for`'s cyclomatic ~12). |
| `tests/acceptance/test_scoring_calibration.py` (new) | `ANALYSIS_ONLY` run over `build_scoring_repo` + `build_test_repo`; asserts `pricing_engine` → HIGH/CRITICAL legacy risk + RISKY/CRITICAL hotspot + materially-lower change-safety than `tax_rules`; `tax_rules` → LOW legacy + STABLE/WATCH hotspot + SAFE/CAUTION change-safety. A scale change that mis-ranks a fixture now fails a test. |
| `core/versions.py` | `legacy_risk` → v2, `understanding` → v2, `coverage_refine` added; `change_safety` stays v1. |
| `tests/integration/test_scoring_pipeline.py` | one pinned `engine_version == "legacy_risk.v1"` assertion → `"legacy_risk.v2"`. |
| `tests/acceptance/test_end_to_end.py` | now also asserts that after a FULL run every `LegacyDNA` row has `coverage_is_proxy is False` and at least one has a real `failure_count > 0`. |

### Key design decisions

**Post-`EXECUTING` refinement, not a prior-run lookup.** `BUILDING_LEGACY_DNA` /
`SCORING_HOTSPOTS` run before the sandbox produces `coverage.xml`. Rather than read a
*previous* run's coverage (which fights the snapshot-scoped result-clone path and needs
a two-run test), the refinement runs inside `_executing` - which already reads
`coverage.xml` for test-gap analysis - and rewrites this run's rows in place.
**`ANALYSIS_ONLY` runs never reach `EXECUTING`, so they keep the presence proxy and the
~4 Phase-5/6 acceptance tests that pin `coverage == 0.5` do not break** (they were
switched to `ANALYSIS_ONLY` in Phase 14).

**`failure_count` is backfilled at `DETECTING_FAILURES`, not `EXECUTING`.** Failures are
detected the stage *after* `EXECUTING`, so `backfill_failure_counts` is a separate small
pass. `LegacyDNA.failure_count` is now real (count of this run's failures whose frames
resolve to the component) instead of always `None`, but `legacy_risk_score` still omits
it from the score - adding it as a weighted signal would rebalance every score and
re-pin every scoring test, a deliberate future calibration step (documented in
`legacy_risk.py`).

**`pricing_engine` lands CAUTION on change-safety** (not RISKY) with the current
constants - the calibration test asserts the *ordering* (`tax_rules` safer by > 10
points) and flags this as a known follow-up recalibration rather than silently
tightening the weights and re-pinning Phase 6.

## Tests

`ruff check archon tests alembic` clean.

| Tier | Result |
|---|---|
| `test_scoring_calibration.py` (2) | green |
| `test_{legacy_risk,hotspot,change_safety,repository_understanding}_scoring.py` + `test_scoring_properties.py` | green - `understanding.v2` weights still satisfy "all 1.0 → 100.0"; `coverage_is_proxy` default keeps `legacy_risk` numbers identical for the existing cases |
| `test_end_to_end.py` (FULL, Docker) | green - `coverage_is_proxy` flips, `failure_count` filled |
| `test_phase5_scoring.py` / `test_phase6_change_safety.py` (`ANALYSIS_ONLY`) | green - proxy unchanged |

## Known limitations / deferred

* **`ChangeAssessment` is not refined** post-`EXECUTING` (signal reconstruction cost);
  it keeps the presence-proxy coverage. `change_safety` stays `v1`.
* **`failure_count` is out of the score** - wiring it into the formula + rebalancing
  weights + re-pinning tests is a `legacy_risk.v3` calibration step.
* **`pricing_engine` change-safety = CAUTION** - a weight recalibration to push it to
  RISKY is a documented follow-up.
