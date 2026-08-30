# Phase 3 — Architecture & Dependency Intelligence — Completion Record

Per spec §62 step 11 and the plan's per-phase completion gate. Builds on Phases 1–2.

## Scope delivered

Two pipeline stages that turn the flat component model into an architecture, run for
`ANALYSIS_ONLY` / `FULL`:

```
… ANALYZING_SOURCE
   ─▶ BUILDING_GRAPH               NetworkX component + module graphs;
                                   derive DEPENDS_ON + TESTED_BY edges; cycle detection
   ─▶ RECONSTRUCTING_ARCHITECTURE  role per module (roles.v1); fan-in/out, instability,
                                   betweenness, PageRank; layering check; graph artifact
```

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Graphs | `archon/analysis/graph/builder.py` | `build_component_graph` (MultiDiGraph of every component + resolved edge), `build_module_graph` (collapse to MODULE nodes; edge `weight` + contributing `kinds`) |
| Derived edges | `archon/analysis/graph/derive.py` | idempotent per snapshot; `DEPENDS_ON` (module→module), `TESTED_BY` (tested module → test module); `find_cycles` (SCC + `simple_cycles`, capped, + self-loops) |
| Roles | `archon/analysis/architecture/roles.py` | `roles.v1` — explicit ordered decision procedure `test→config→entrypoint→api→cli→model→io→util→domain→unknown`; keyword lists in-module; `layering_violation` rules |
| Metrics | `archon/analysis/architecture/metrics.py` | `arch_metrics.v1` — fan_in/out, instability, degree/betweenness centrality, pure-Python PageRank (no numpy), `in_cycle`/`scc_size`, `dependents`/`dependencies` |
| Reconstruct | `archon/analysis/architecture/reconstruct.py` | mirrors module role onto FILE/CLASS/FUNCTION/METHOD descendants + config files; stores `Component.metrics["architecture"]`; layering check; writes artifact; classified evidence; snapshot-cached |
| Artifact store | `archon/core/artifacts.py` | `write_json` / `read_json` → `<artifact_root>/<run_id>/<kind>.json` + sha256 + size, one `analysis_artifacts` row per (run, kind) |
| Schema | `alembic/versions/0003_architecture.py` | `Dependency.kind` → plain VARCHAR via `EnumString` (`db/types.py`); `DependencyKind` completed (TESTED_BY + git/failure kinds); drop+recreate the derived `dependencies` table |
| Pipeline | `archon/pipeline/orchestrator.py` | `_STAGE_PLANS` gains `BUILDING_GRAPH`, `RECONSTRUCTING_ARCHITECTURE`; `_graph` + `_architecture` stage methods; `graph.v1`/`roles.v1`/`arch_metrics.v1`/`architecture.v1` in the version registry |
| API | `archon/api/routers/architecture.py` | `GET /runs/{id}/architecture`, `GET /runs/{id}/architecture/graph`, `GET /snapshots/{id}/modules` (`role` / `in_cycle` filters); `/snapshots/{id}/dependencies` now serves DEPENDS_ON / TESTED_BY |
| Frontend | `frontend/src/App.tsx`, `api.ts` | "Architecture" panel on completed runs — role histogram, module table (role, fan in/out, instability, betweenness, in-cycle), cycle/violation list, inline-SVG module graph coloured by role |

## Tests — `cd backend && pytest`

**149 passed** (was 112; +37 for Phase 3). `ruff check archon tests alembic` clean.

| Tier | Files | Covers |
|---|---|---|
| unit | `test_roles` (one case per precedence branch + layering rules), `test_arch_metrics_and_cycles` (fan in/out, instability, betweenness bridge, SCC/`in_cycle`, `find_cycles` on DAG / 2-cycle / 3-cycle / self-loop) | 24 cases |
| integration | `test_module_graph` (collapse + weight/kinds, no transitive/intra-module edges), `test_architecture_pipeline` (roles on every component, DEPENDS_ON=5 / TESTED_BY=2, `metrics.architecture` persisted, artifact on disk with matching sha256, snapshot caching), `test_architecture_api` (every endpoint + filters + 404/409) | |
| acceptance | `test_phase3_architecture` | exact fixture role histogram `{domain:3, model:1, test:3, unknown:1}`; exact DEPENDS_ON + TESTED_BY edge sets; `legacy_shop.billing` highest betweenness; 0 cycles; 0 layering violations; classified `graph.v1`/`architecture.v1` evidence; engine-version pinning; cached re-run |

Two Phase-2 tests that over-asserted `last_completed_stage is ANALYZING_SOURCE` for
`ANALYSIS_ONLY` were updated to `RECONSTRUCTING_ARCHITECTURE` (the mode now runs the full
analysis prefix).

## Verified manually

* `archon analyze ./shop --mode full --wait` → `COMPLETED` at `RECONSTRUCTING_ARCHITECTURE`;
  evidence "Module dependency graph: 8 modules, 5 DEPENDS_ON edges, 2 TESTED_BY edges" and
  "Reconstructed architecture: 8 modules (domain=3, model=1, test=3, unknown=1)";
  `<artifact_root>/<run_id>/architecture_graph.json` written (21 KB).
* HTTP: `GET /runs/{id}/architecture` → role histogram + per-module metrics, `cycles: []`,
  `layering_violations: []`; `GET /runs/{id}/architecture/graph` → `schema: archon.graph.v1`,
  8 module nodes / 5 edges; `GET /snapshots/{id}/modules?role=domain` → the 3 domain modules.
* `alembic upgrade head` applies `0002 → 0003` cleanly on SQLite; `dependencies.kind` is now
  plain `VARCHAR(40)`.
* `frontend: npm run build` clean.

## Known limitations / deferred

* Module graph edges come from resolved IMPORTS/CALLS/INHERITS only; unresolved external
  references are not graph edges (they remain queryable `dependencies` rows).
* CHANGED_BY / CHANGED_WITH (Phase 4, git) and FAILED_IN / FIXED_BY / AFFECTS (Phase 9)
  are declared in `DependencyKind` but not yet populated.
* Layering check is deliberately conservative (only lower→`api`/`cli`/`entrypoint` and
  non-test→test); richer clean-architecture rules can come with Phase 5 tech-debt.
* `betweenness_centrality` on large module graphs is O(V·E); fine at fixture scale, revisit
  with a sampling cutoff if a real repo has thousands of modules.
