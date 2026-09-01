# Phase 10 — Incident Memory — Completion Record

Per the plan's Phase 10 scope (§44) and the per-phase completion gate. Builds on
Phase 9's failure investigation & self-healing. The last of the currently-declared
`Stage` values before `MODERNIZING` (Phase 12) — `RECORDING_INCIDENT` fills the final
gap in `_ANALYSIS_STAGES`.

## Scope delivered

```
… REGRESSION_VERIFYING
   ─▶ RECORDING_INCIDENT   on a VERIFIED patch, record an Incident; future
                           investigations of a similar failure retrieve and cite it
```

### Key design decisions

**Incidents are repository-scoped, not run/snapshot-scoped.** A later commit changes
`Component`/`RepositorySnapshot` ids, so `failure_signature` deliberately excludes
`component_id` and line numbers, keying instead on `exception_type` + the innermost
stack frame's `(path, func)` — stable across commits of the same repo. Retrieval
(`find_similar_incidents`) queries by `(repo_id, failure_signature)` across every
prior run of that repository, not just the current snapshot.

**History is cited, never substituted (Principle 15).** `investigation/engine.py`
looks up similar incidents *before* calling the AI and always records
`Investigation.cited_incident_ids` (empty if none) — but the mock's
`_op_root_cause_analysis` only appends one sentence to `reasoning_summary` citing the
prior incident id(s); the hypothesis statement, confidence, and evidence are computed
exactly as they would be with zero history. The acceptance test proves this directly:
a second run's investigation confidence is bit-for-bit identical to the first run's.

**`Investigation.cited_incident_ids` required a schema change to an existing table.**
Since `investigations` is fully-derived (rebuilt every run), the migration reuses the
exact drop-table-and-recreate-from-metadata pattern `0003_architecture.py` already
established for widening `dependencies` — simpler and more honest than a
column-by-column `ALTER TABLE` for a table nothing depends on preserving row-for-row.

**`Incident.run_id` isn't in the spec's exact field list** but was added anyway (the
same pragmatic-addition precedent as `Patch.old_snippet`/`new_snippet` in Phase 9) —
without it, re-entering `RECORDING_INCIDENT` on a resumed run has no way to find and
clear its own prior rows before re-inserting, since an incident otherwise has no
run-scoped identity at all (by design - it's meant to outlive the run that created
it).

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Incident store + retrieval | `archon/incidents/store.py` | `compute_failure_signature`, `find_similar_incidents`, `record_incidents` (the `RECORDING_INCIDENT` stage body - one `Incident` per `VERIFIED` `Patch` this run) |
| Investigation | `archon/investigation/engine.py` | Looks up similar incidents before every AI call; persists `cited_incident_ids` |
| Mock AI | `providers/ai/mock.py::_op_root_cause_analysis` | Cites (never uses to infer) historical incidents in `reasoning_summary` |
| Schema | `alembic/versions/0010_incidents.py` | `incidents` (new); `investigations` (drop+recreate, gains `cited_incident_ids`) |
| Pipeline | `archon/pipeline/orchestrator.py` | 1 new stage/dispatch method (`_recording_incident`, MVP-loop - no try/except); 1 new `PipelineResult` field |
| API | `archon/api/routers/incidents.py` (new file) | `GET /runs/{id}/incidents` (recorded by this run), `GET /repositories/{id}/incidents` (full repo history, `created_at` desc) |
| Frontend | `frontend/src/App.tsx`, `api.ts` | Incident Memory panel |

## Tests — `cd backend && pytest`

Full suite green (~330 tests). `ruff check archon tests alembic` clean.
`alembic upgrade head` / `downgrade -1` round-trips cleanly (including the
`investigations` drop+recreate).

| Tier | Files | Covers |
|---|---|---|
| unit | `test_incident_signature.py` | signature determinism, line-number independence, differs by exception type/innermost frame |
| integration | `test_incidents_api.py` (real Docker) | both endpoints, 404s |
| acceptance | `test_phase10_incident_memory.py` (real Docker, skips cleanly if the daemon/image is missing) | run 1 records one incident; run 2's investigation cites it (`cited_incident_ids`) with its own confidence unchanged; run 2 also records its own (different) incident |

## Verified manually

* A manual two-run script confirmed the full story end-to-end before the formal
  acceptance test was written: run 1 → 1 incident; run 2 → `cited_incident_ids`
  contains run 1's incident id, `confidence` identical (0.9 both runs).
* Full backend suite (`pytest`, no filters) exits 0 with Docker Desktop running
  throughout; zero orphaned containers after the run.
* `npm run build` clean.

## Known limitations / deferred

* **Retrieval is exact-signature match only** - the spec also mentions "stack +
  component overlap" as a fuzzier retrieval signal; not needed to satisfy this
  phase's acceptance bar (only one bug pattern is recognized end-to-end), but a
  natural extension once a real AI provider recognizes more patterns.
* **`MODERNIZING` remains unwired** - Phase 12's job, out of scope here.
* **No incident-browsing UI beyond the per-run panel** - `GET /repositories/{id}/incidents`
  exists and is exercised by tests, but the frontend only surfaces incidents recorded
  by the currently-viewed run, not a dedicated cross-run history browser.
