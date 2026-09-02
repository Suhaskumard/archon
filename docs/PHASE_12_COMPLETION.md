# Phase 12 — Modernization — Completion Record

Per the plan's Phase 12 scope (§46) and the per-phase completion gate. The final
phase: it wires `MODERNIZING` — the last declared `Stage`, `RECORDING_INCIDENT`'s
successor in `STAGE_ORDER` and the one value never in the orchestrator's
`_ANALYSIS_STAGES` — so a run now ends by turning its deterministic findings into an
ordered, evidence-backed modernization plan. All 12 phases are implemented; the
closed loop runs end to end.

## Scope delivered

```
… RECORDING_INCIDENT
   ─▶ MODERNIZING   assemble deterministic targets (legacy risk ≥ MODERATE, tech-debt
                    findings, WATCH+ hotspots, import cycles)
                    ─▶ AI modernization_recommendation (mock): strategy / risk / effort /
                       impact / rationale per target
                    ─▶ deterministic modernization.v1 ordering: dependencies first
                       (condensed module import graph), add_tests before structural
                       strategies, safer-first by change safety
                    ─▶ one ModernizationRecommendation row per step + one RECOMMENDATION
                       Evidence row per step
```

### Key design decisions

**`MODERNIZING` is wired by appending one value to `_ANALYSIS_STAGES`.** `STAGE_ORDER`
in `jobs/state_machine.py` already ended with `MODERNIZING`, so `RunStateMachine` /
`next_stage` / `stage_index` and `test_state_machine.py` needed no change.
`tests/conftest.py::terminal_stage("FULL")` is computed from `_STAGE_PLANS[...][-1]`,
so it advances to `MODERNIZING` on its own and every `assert run.last_completed_stage
is terminal_stage("FULL")` (Phases 2–11) keeps passing untouched. `comparison.py`'s
`_ANALYSIS_STAGES.index(ASSESSING_CHANGE_SAFETY)` is unaffected by an append.

**Degrade-and-continue, not MVP-loop.** Modernization is advisory analysis, not part
of the self-healing loop, so `_modernizing` follows the Phase 8 `GENERATING_TESTS`
pattern: the `complete_structured` call is wrapped in `try/except (AIProviderError,
AIOutputError)` → a FACT Evidence row and an empty plan on failure, never a failed
run. A run with no modernization-worthy component also completes normally with a
single FACT Evidence ("repository is in good shape").

**The safe *ordering* is deterministic, never the AI's job** (spec: "sequencing
derived from the dependency + change-safety graph"). `modernization.v1`
(`modernization/planner.py::compute_safe_order`) reuses
`analysis/graph/builder.py::build_module_graph` + `nx.condensation` (so the fixture's
deliberate `pricing_engine ↔ discount_rules` import cycle doesn't break the
topological sort), orders SCCs dependencies-first, then sorts within a generation by
`(strategy_rank, -change_safety_score, legacy_risk_score, target)` — `add_tests` (0) <
`extract_dependency`/`replace_dependency` (1) < `refactor` (2) < `rewrite` (3). Every
row carries a `breakdown` in its Evidence refs.

**`rewrite` is never a default (Principle 12).** The mock emits `rewrite` for a target
*only* when its legacy category is `CRITICAL` **and** none of the four cheaper
strategies (tests / extract / replace / refactor) applied to it. In the acceptance
fixture — where `pricing_engine` has a coverage gap, an import cycle and refactor
smells — a cheaper strategy always fires, so no `REWRITE` row is produced, exactly as
the spec's acceptance bar requires.

**Mock scope discipline.** `_op_modernization_recommendation` recognizes a fixed
finding→strategy mapping (coverage gap + HIGH/CRITICAL risk → `add_tests`; cycle /
`CIRCULAR_DEPENDENCY` → `extract_dependency`; `DEPRECATED_API` → `replace_dependency`;
complexity/coupling or a structural smell → `refactor`), not general modernization
reasoning. `targets == []` → `recommendations: []`, `confidence: UNKNOWN` — no
fabricated advice, matching every other Mock op.

**Targets are modules.** Legacy DNA / change safety / hotspots are scored per
component (module/class/function); tech-debt findings hang off file/function/class
components. The planner rolls everything up to the owning **module** (shared path) so
`target` is a stable module `qualified_name` that lines up with the module import
graph used for ordering — the same "stable name, snapshot ids churn" reasoning as
`Incident` / `RepositoryComparison`.

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Planner | `archon/modernization/planner.py` | `assemble_targets` (candidate filter + signal rollup), `compute_safe_order` (deterministic `modernization.v1` ordering), `generate_modernization_plan` (the stage body) |
| AI schema | `archon/domain/ai_schemas.py` | `ModernizationItem`, `ModernizationRecommendation`, `MODERNIZATION_SCHEMA_VERSION`; added to `SCHEMA_VERSIONS` + `__all__` |
| Mock AI | `archon/providers/ai/mock.py::_op_modernization_recommendation` | fixed finding→strategy mapping; never `rewrite` when a cheaper option fired |
| Enum | `archon/domain/enums.py` | `ModernizationStrategy` (`_enum()`-backed) |
| Model | `archon/db/models.py` | `ModernizationRecommendation` (new); `__all__` |
| Schema | `alembic/versions/0012_modernization.py` | `modernization_recommendations` (new); copy of the `0011_comparison.py` create/drop pattern, no existing-table change |
| Engine versions | `archon/core/versions.py` | `"modernization": "modernization.v1"`, `"ai_modernization_recommendation": "modernization_recommendation.v1"` |
| Pipeline | `archon/pipeline/orchestrator.py` | `Stage.MODERNIZING` in `_ANALYSIS_STAGES`; `_modernizing` dispatch method; 1 new `PipelineResult` field |
| API | `archon/api/routers/modernization.py` (new) | `GET /runs/{id}/modernization` (ordered by `order_index`, `strategy` filter); registered in `api/app.py`; `ModernizationRecommendationOut` |
| Frontend | `frontend/src/App.tsx`, `api.ts` | Modernization panel (ordered table, strategy pills, confidence + classification) |

## Tests — `cd backend && pytest`

`ruff check archon tests alembic` clean. `alembic upgrade head` / `downgrade -1`
round-trips (verified). The unit + integration tiers need no Docker; the acceptance
tier is gated on `sandbox_image_available` and skips cleanly without the
`archon-sandbox:latest` image, exactly like Phases 7–11.

| Tier | File | Covers |
|---|---|---|
| unit | `tests/unit/test_modernization_planner.py` | mock finding→strategy mapping (add_tests for untested HIGH risk; never rewrite when cheaper fires; empty→UNKNOWN); `assemble_targets` filters a clean module; `compute_safe_order` orders a dependency before its dependent and `add_tests` before `refactor`, assigns contiguous `order_index`, and is deterministic; `generate_modernization_plan` end-to-end persists rows with the same ordering and no `REWRITE` |
| integration | `tests/integration/test_modernization_api.py` | `GET /runs/{id}/modernization` returns rows ordered by `order_index` with `add_tests` before `refactor` for the risky target, `component_qn` resolved, one Evidence per rec; `strategy` filter; 404 unknown run, 409 snapshot-less run |
| acceptance | `tests/acceptance/test_phase12_modernization.py` (real Docker) | full worker over `scoring_repo` → `COMPLETED`, `last_completed_stage is terminal_stage("FULL") is Stage.MODERNIZING`; `pricing_engine` gets `ADD_TESTS` before `REFACTOR`; no `REWRITE` anywhere; every rec evidence-backed with a valid confidence |

## Verified manually

* `pytest tests/unit/test_modernization_planner.py tests/integration/test_modernization_api.py`
  — green (9 tests).
* `alembic upgrade head` → table present; `downgrade -1` → gone; re-`upgrade` clean.
* `cd frontend && npm run typecheck && npm run build` — clean.
* The acceptance test **skips** in this environment (no sandbox image), same disclosure
  as Phases 7–11; its full-pipeline path was not run here.

## Known limitations / deferred

* **Acceptance test needs the Docker sandbox** to drive a `FULL` run to `COMPLETED`
  (`MODERNIZING` runs after `EXECUTING`). The whole Phase 12 code path (assemble →
  mock op → order → persist → API) is covered sandbox-free by the unit + integration
  tiers.
* **No Excel "Modernization" sheet** — all Excel reporting / the `reporting/` package
  (§49–50) remains unbuilt across every phase.
* **`rewrite` is reachable but rare** — the mock only emits it for a `CRITICAL` target
  with no cheaper strategy; a real `ClaudeAIProvider` would weigh rewrite-vs-refactor
  with judgement the deterministic mapping can't.
* **No manifest-level deprecated-dependency scan** — "deprecated deps / legacy APIs"
  maps onto the existing AST `DEPRECATED_API` tech-debt findings only (no
  `requirements.txt` / `pyproject.toml` EOL-package lookup).
* **Recommendations are advisory** — exported as rows for a human to sequence and
  execute; nothing is auto-applied (Principle 11, consistent with patches in Phase 9).
