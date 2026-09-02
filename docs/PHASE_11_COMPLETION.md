# Phase 11 — Repository Comparison — Completion Record

Per the plan's Phase 11 scope (§45) and the per-phase completion gate. Builds on the
analysis engines of Phases 2–6 (architecture, dependencies, Legacy DNA, technical
debt, risk, change safety) — comparison reads their persisted rows for two runs and
reports the delta.

## Scope delivered

```
run @ commit A ─┐
                ├─▶  POST /repositories/{id}/comparisons {base_run_id, head_run_id}
run @ commit B ─┘         │
                          ├─ differ.compute_comparison   deterministic diff, keyed by qualified_name
                          │     architecture · dependencies · legacy_dna · risk · coverage · technical_debt · change_safety
                          ├─ store.build_comparison      upsert RepositoryComparison row (one per run pair)
                          └─ core.artifacts.write_json   full report as an AnalysisArtifact  (spec: "report as artifact")
```

### Key design decisions

**On-demand, not a pipeline `Stage`.** Comparison needs two runs that already exist,
so — exactly like `POST /runs/{id}/change-impact` (Phase 6) — it is an API-triggered,
persisted computation, not a single-run stage. Nothing in `Stage` / `STAGE_ORDER` /
`_ANALYSIS_STAGES` / `PipelineResult` / `terminal_stage` changes, so no pre-existing
pinned test shifts. The completion gate's "wired into the pipeline" is read here as
"a first-class persisted operation with an API route + screen", the same latitude
change-impact already took.

**Diff on `qualified_name`, never `component_id`.** Component ids are snapshot-scoped
and change between commits (the same fact behind Phase 10's failure signature).
`differ.py` builds a `{component_id → qualified_name}` map per snapshot and keys every
section on the stable name.

**Guard is "analysis scored", not "COMPLETED".** Every diffed table is written by
`ASSESSING_CHANGE_SAFETY`; a run that reached that stage is comparable even if a later
MVP-loop stage (execution / healing) failed it. The API accepts any run with a
snapshot whose `last_completed_stage` is at or past `ASSESSING_CHANGE_SAFETY`. This
keeps the unit + integration tests sandbox-free — only the acceptance test needs
Docker (a `FULL` run to `COMPLETED`), matching the Phase 9/10 precedent.

**One row per ordered `(base_run, head_run)` pair**, upserted on recompute
(`uq_comparison_run_pair`) — the same idempotent-upsert convention
`core/artifacts.write_json` and `ChangeImpact` use. Artifact `kind` is
`repo_comparison_<comparison_id>` (underscore, not `:` — colons are illegal in
Windows filenames and `write_json` writes `<kind>.json`).

**Change-safety regression = score drop.** `safety_score` is inverse-sense (higher =
safer), so `differ._diff_change_safety` flags a component as regressed when the score
falls or the `ChangeSafetyCategory` worsens — unlike Legacy Risk where a rise is the
regression.

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Differ | `archon/comparison/differ.py` | `compute_comparison` + one `_diff_*` per section; `_qn_by_id` cross-snapshot key; antisymmetric under base/head swap |
| Persistence | `archon/comparison/store.py` | `build_comparison` (compute-or-return-cached), `find_existing_comparison`; writes the `RepositoryComparison` row + report artifact |
| Model | `archon/db/models.py` | `RepositoryComparison` (repo-scoped, `summary` + `report` JSON, `report_artifact_id`) |
| Schema | `alembic/versions/0011_comparison.py` | `repository_comparisons` (new); copy of the `0009_healing.py` create/drop pattern, no existing-table change |
| Engine version | `archon/core/versions.py` | `"comparison": "comparison.v1"` |
| API | `archon/api/routers/comparison.py` (new) | `POST /repositories/{id}/comparisons`, `GET /repositories/{id}/comparisons`, `GET /comparisons/{id}`; guards → `409` / `404` |
| Schemas | `archon/api/schemas.py` | `ComparisonCreate`, `ComparisonSummaryOut`, `ComparisonOut` |
| Frontend | `frontend/src/api.ts`, `App.tsx`, `vite.config.ts` | `RepositoryComparisonPanel` (baseline-run picker → delta tables), `/comparisons` proxied |

## Tests — `cd backend && pytest`

`ruff check archon tests alembic` clean. `alembic upgrade head` / `downgrade -1`
round-trips (verified).

| Tier | File | Covers |
|---|---|---|
| unit | `tests/unit/test_comparison_differ.py` | added/removed modules & dependency edges; legacy-risk delta + category regression; change-safety regression; coverage-proxy flag + worse list; tech-debt resolve tracking; antisymmetry under base/head swap. Hand-built rows in a real session — no worker, no Docker. |
| integration | `tests/integration/test_comparison_api.py` | all 3 endpoints end-to-end against two directly-built analysis-complete runs; idempotent recompute; summary list omits `report`; artifact row written & owned by the head run; guard paths (`base == head` 409, cross-repo 409, unknown ids 404, not-yet-scored run 409). No Docker. |
| acceptance | `tests/acceptance/test_phase11_comparison.py` | the spec bar — `test_repo` analysed at commit 1 vs commit 3 (`FULL` runs): the diff names an added module (`legacy_shop.inventory`) **and** shows a risk / change-safety movement (`billing` was guarded between the commits); report retrievable as an artifact; recompute returns the same row. Skips cleanly without `archon-sandbox:latest` (same as Phase 9/10). |

## Verified manually

* `pytest tests/unit/test_comparison_differ.py tests/integration/test_comparison_api.py`
  — green (13 tests).
* `alembic upgrade head` → table present; `downgrade -1` → gone; re-`upgrade` clean.
* `cd frontend && npm run typecheck && npm run build` — clean.
* The acceptance test **skips** in this environment (no Docker image) exactly like
  `test_phase9_healing.py` / `test_phase10_incident_memory.py`; its full-pipeline path
  was not run here.

## Known limitations / deferred

* **Acceptance test needs the Docker sandbox** to drive two `FULL` runs to
  `COMPLETED` — same disclosure as Phases 9–10. The whole Phase 11 code path
  (differ → store → artifact → router → guards) is covered sandbox-free by the unit +
  integration tiers.
* **No Excel "Comparison" sheet** — all Excel reporting (§49–50) remains unbuilt.
* **Section matching is exact** — modules/edges/debt by identity, no rename or
  fuzzy-move detection (a renamed module reads as one removed + one added).
* **Coverage is the Legacy-DNA proxy value**, not a measured run; the report and the
  UI both flag it (`is_proxy`, footnote `*`).
* **`MODERNIZING` still unwired** — Phase 12.
