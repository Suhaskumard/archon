# Phase 8 — Characterization & Test-Gap Analysis — Completion Record

Per the plan's Phase 8 scope (§33-35) and the per-phase completion gate. Builds on
Phase 7's Docker sandbox and existing-test execution engine. Replaces the two honest
stubs Phase 7 left behind (`CHARACTERIZING`, `GENERATING_TESTS`) with real work, and
adds real coverage-based test-gap analysis at `EXECUTING`.

## Scope delivered

```
… ANALYZING_TESTS   existing-test discovery (Phase 7) + structural test-gap candidates
   ─▶ CHARACTERIZING    bounded-input characterization baselines, captured in the sandbox
   ─▶ GENERATING_TESTS  AI (mock) test generation, static- + sandbox-validated
   ─▶ EXECUTING         combined suite run, real coverage.xml parsed, TestGap rows ranked
```

### Key design decision: stage-order sequencing

`STAGE_ORDER` is fixed and append-only - Phase 8 fills the four already-reserved slots
rather than adding new ones. Since `EXECUTING` (which produces this run's
`coverage.xml`) runs *after* `CHARACTERIZING`/`GENERATING_TESTS`, those two stages
can't use this run's own coverage data to pick targets. Resolved by splitting
responsibility by data source: `ANALYZING_TESTS` computes a cheap *structural*
candidate list (`testing/gaps.py::identify_untested_components` - no discovered test
name naively matches the function); `CHARACTERIZING`/`GENERATING_TESTS` consume that
list; `EXECUTING` runs the *combined* suite (existing + characterization + AI-generated
files, all copied into the workspace by the earlier stages) and only then computes the
real, coverage-informed `TestGap` ranking.

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Coverage parsing | `archon/testing/coverage.py` | `parse_coverage_xml` (Cobertura format) + `component_coverage_pct`. `execution/runner.py`'s pytest command gained `--cov-branch`. |
| Test-gap analysis | `archon/testing/gaps.py` | `identify_untested_components` (structural) + `analyze_test_gaps` (coverage-informed, joins this run's `LegacyDNA`/`ChangeAssessment` rows, weights: risk 0.4, danger 0.4, coverage-gap 0.2, historical-failures 0.0/documented). Persists `TestGap`. |
| Characterization | `archon/testing/characterization.py` | `assess_target_safety` (rejects decorated/varargs/side-effecting targets), `generate_bounded_inputs` (deterministic uniform-value sets), `run_characterization` - writes a harness script into the workspace, runs it via the sandbox, captures per-input output/exceptions, emits a pytest characterization test, persists `Characterization` + `TestCase(kind=CHARACTERIZATION)`. |
| AI test generation | `archon/testing/generation.py` | `run_test_generation` - calls the mock `TestGeneration` AI op once per candidate, static-validates each scenario, batches the statically-valid ones into **one** sandbox run per candidate (see "Design findings"), persists `TestCase(kind=<scenario kind>, origin=AI, validated=...)`. |
| Shared safety | `archon/testing/_safety.py` | `source_is_safe` (banned-construct scan) + `parses` (syntax check), shared by characterization and generation. |
| AI schema | `domain/ai_schemas.py` | `TestScenario`, `TestGeneration(AIEnvelope)`; `MockAIProvider._op_test_generation` (mock.py) - deterministic, template-based scenario generation from signature/source scans. |
| Schema | `alembic/versions/0008_characterization.py` | `characterizations`, `test_gaps` |
| Enums | `domain/enums.py` | `TestGapKind`, `TestGapPriority` (`_enum()`-backed, closed vocabulary) |
| Pipeline | `archon/pipeline/orchestrator.py` | `_characterizing`/`_generating_tests` widened to real dispatches (were 2-arg stubs, now take `snapshot`/`workspace` like every other stage); `_analyzing_tests`/`_executing` extended in place - no new stages, no `PipelineResult` field changes. |
| API | `archon/api/routers/execution.py` | `GET /runs/{id}/characterization`, `GET /runs/{id}/test-gaps` (sorted by `priority_score` desc, optional `priority` filter) |
| Frontend | `frontend/src/App.tsx`, `api.ts` | `CharacterizationPanel`, `TestIntelligencePanel` (test-gap table with risk/safety/coverage/priority columns) |

## Design findings (discovered empirically this phase, not assumed)

* **One container per AI scenario was far too slow.** The first implementation spun up
  a separate sandbox container per generated scenario (up to 6 per candidate) *and*
  per characterization target (up to 5) - on Docker Desktop, each container spin-up
  (create/start/copy-in/exec/copy-out/rm) costs multiple seconds, so a single FULL
  pipeline run could spawn 30+ containers and full-suite runs that previously took
  under 8 minutes started hanging past 5+ minutes per test. **Fix**: batch all of a
  generation candidate's statically-valid scenarios into **one** rendered file and run
  it through the sandbox **once** (validated = "collected and ran", not "each scenario
  individually sandboxed"); capped both `characterization.py` and `generation.py` to 3
  candidate targets per run (`_MAX_TARGETS`). This cut per-run container count from
  30+ to ~7 (3 characterization + 3 generation + 1 combined `EXECUTING` run) and
  brought full-suite runtime back in line with Phase 7's.
* **`DockerSandbox._create`/`_start`/the tar-based copy-in/copy-out calls had no
  timeout** - only `_exec` (the actual command) did. Added a 30s
  `_CONTROL_TIMEOUT_SECONDS` bound to all of them so an unresponsive daemon fails fast
  with a typed `ArchonError` instead of blocking the pipeline indefinitely.
* **Global module state must be reset between characterization inputs.** The fixture's
  known gap (`inventory.reserve`) mutates a module-level `_STOCK` dict; running all
  bounded inputs in one harness process required explicitly clearing
  `sys.modules[MODULE...]` and re-importing before every call, or later inputs would
  see state left over from earlier ones and the baseline would not be reproducible.
* **Coverage retrofit into `LegacyDNA`/`ChangeAssessment` was deliberately scope-cut.**
  Both engines' `coverage` field stays the documented `TESTED_BY`-edge proxy from
  Phases 5-6 - wiring in real coverage would touch code whose acceptance tests pin
  exact numeric scores, for a marginal gain, since `TestGap.coverage_pct` already
  carries the real, parsed number directly into test-gap prioritization (the actual
  spec deliverable).

## Tests — `cd backend && pytest`

Full suite green (unit + integration + acceptance, ~300 tests). `ruff check archon
tests alembic` clean. `alembic upgrade head` / `downgrade -1` round-trips cleanly.

| Tier | Files | Covers |
|---|---|---|
| unit | `test_coverage_parsing.py`, `test_characterization_safety.py` | Cobertura XML parsing + per-component coverage math; safety-gate accept/reject cases; deterministic bounded-input generation |
| integration | `test_gap_identification.py` (no Docker - pure DB query) | structural candidate heuristic excludes naively-matched functions, respects `limit` |
| integration | `test_characterization_api.py` (real Docker) | `/runs/{id}/characterization` and `/runs/{id}/test-gaps` end-to-end over HTTP - shapes, priority sort order, `priority` filter, 404s |
| acceptance | `test_phase8_characterization.py` (real Docker, skips cleanly if the daemon/image is missing) | the fixture's known gap (`inventory.reserve`) is found in `TestGap` with `UNTESTED_FUNCTION`/`coverage_pct=0.0`/priority above the floor; a `Characterization` baseline is byte-identical across two runs of the same commit; at least one AI-generated `TestCase` is `validated=True` |

Two Phase 7 tests were updated (not regressed): `test_execution_api.py` and
`test_phase7_sandbox.py` hardcoded `len(test_cases) == 2` / `len(executions) == 1` for
a FULL run - both now filter by `kind=EXISTING_TESTS`/`EXISTING`, since Phase 8
legitimately adds more `TestCase`/`Execution` rows for the same run.

## Verified manually

* Full backend suite (`pytest`, no filters) exits 0 with all Docker-dependent tests
  included, Docker Desktop running throughout.
* `test_repo`'s `inventory.reserve` (the fixture's `# KNOWN TEST GAP`) verified present
  in `TestGap` results end-to-end through a live pipeline run.
* HTTP: `/runs/{id}/characterization` and `/runs/{id}/test-gaps` verified against a
  live completed run via `test_characterization_api.py` (`TestClient`, real Docker).
* Frontend: `npm run build` clean (TypeScript + Vite, no errors). The new panels
  follow `TestExecutionPanel`'s exact fetch/render skeleton and the same `req<T>`
  API-client pattern already browser-verified in Phase 7 - **not** re-verified in a
  live browser this phase; do so before relying on their rendering in production.
* No orphaned containers left behind after any test run.

## Known limitations / deferred

* **Only two of the five declared `TestGapKind` values are actually distinguished**
  (`UNTESTED_FUNCTION` for 0% coverage, `MISSING_EDGE_CASE` for partial) -
  `MISSING_EXCEPTION_TEST`/`MISSING_REGRESSION_TEST`/`MISSING_CHARACTERIZATION` are
  declared vocabulary for a future, more precise engine, matching the project's
  "declare the full vocabulary, populate the tractable subset" convention.
* **Historical-failures prioritization has no data until Phase 9** - explicitly
  weighted 0 and recorded in `TestGap.factor_breakdown`, never faked.
* **Characterization/generation are scoped to module-level `FUNCTION` components
  only** - `METHOD` targets need instance construction, which this deterministic
  engine cannot safely infer; skips are evidence-backed (`INFERENCE` rows), not
  silent.
* **Coverage retrofit into Legacy Risk/Change Safety is deliberately not done** - see
  "Design findings" above.
* **Each pipeline run is capped at 3 characterization + 3 generation targets** - a
  deliberate runtime bound (see "Design findings"); a larger repo's full gap list is
  still computed and ranked by `analyze_test_gaps` at `EXECUTING`, only the
  characterization/AI-generation *effort* is capped.
