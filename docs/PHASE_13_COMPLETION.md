# Phase 13 — Reporting & bulk I/O — Completion Record

Per `docs/ROADMAP.md` Phase 13 and the spec's cross-cutting Excel section (§49–50), the
last unbuilt named deliverable. ARCHON now produces `ARCHON_Legacy_Analysis.xlsx` (14
sheets) and accepts a `repositories.xlsx` bulk input that enqueues ordinary runs.

## Scope delivered

```
GET /runs/{id}/report.xlsx  ─▶  reporting.workbook.build_report
                                  └─ reporting.queries.*  (thin adapter over the API
                                     router functions — one data path, no new engine)
                                  ─▶ 14 sheets, Response(media_type=xlsx, Content-Disposition)

POST /repositories/bulk  /  archon bulk-import <xlsx>
     ─▶ reporting.bulk_import.import_repositories_xlsx
        └─ provider_for + RepositoryProvider.parse  (validation)
        └─ JobManager.create_run_with_job(priority=…)  (existing enqueue path)
```

### Key design decisions

**`reporting/queries.py` is a thin adapter, not a second query layer.** Spec §49
requires the report be "sourced from the same service/domain layer as the API, no
separate engine". Every Phase-5+ router inlines its own `select` + `*Out` mapper, and
those functions take `(run_id, session, <filters>)` — so `queries.*` calls them
directly with all arguments explicit. The report renders exactly what
`GET /runs/{id}/<resource>` returns; there is no duplicated SQL. (Consolidating the
routers onto a shared read module is Phase 15's de-duplication work.)

**Lazy router import.** `queries._r(name)` imports `archon.api.routers.<name>` on first
use via `importlib` + `functools.cache` — importing them at module top would create a
`reporting ↔ api.app` cycle (`app.py` imports `routers.reporting`, which imports
`reporting.workbook`, which imports `reporting.queries`).

**Artifact-backed resources degrade, don't fail.** `understanding`, `architecture` and
`evolution` raise `ArchonError(CONFLICT)` when their stage has not run; `queries._safe`
catches that and returns `None`, so a partial run still yields a full 14-sheet
workbook (the affected sheet says "not scored for this run").

**Bulk import reuses the exact `POST /repositories/{id}/runs` path.** Per row:
`provider_for` + `.parse` for deterministic validation, upsert `Repository`,
`JobManager.create_run_with_job` with the already-existing `priority` kwarg (the
worker orders by `Job.priority.asc(), created_at.asc()`). A `create_run_with_job`
`ArchonError` (dedupe of an in-flight `repo+config`) → the row is reported `skipped`,
not `error`. No new enqueue code.

**First binary endpoint.** `GET /runs/{id}/report.xlsx` returns
`fastapi.responses.Response(content=<bytes>, media_type=<xlsx>, Content-Disposition)`
and persists the workbook as an `AnalysisArtifact` via the new `core/artifacts.
write_bytes` (a byte-taking copy of `write_text`). `python-multipart` added for the
`UploadFile` on `POST /repositories/bulk`.

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Read layer | `archon/reporting/queries.py` | 19 functions, thin adapters over the router functions |
| Workbook | `archon/reporting/workbook.py` | `build_report` / `report_bytes`; 14 `_sheet_*`; `_write_table` / `_kv` helpers; `SHEET_NAMES` |
| Bulk input | `archon/reporting/bulk_import.py` | `import_repositories_xlsx` → `list[BulkRowResult]` (created / skipped / error) |
| Artifact | `archon/core/artifacts.py` | `write_bytes` / `read_bytes` |
| API | `archon/api/routers/reporting.py` (new) | `GET /runs/{id}/report.xlsx`, `POST /repositories/bulk`; registered in `api/app.py` |
| CLI | `archon/cli/main.py` | `archon report <run_id> [--out]`, `archon bulk-import <xlsx>` |
| Frontend | `frontend/src/{api.ts,App.tsx}` | `api.downloadReport` blob helper + "Download report (.xlsx)" button in `RunView` |
| Deps | `backend/pyproject.toml` | `openpyxl>=3.1`, `python-multipart>=0.0.9` (core) |

## Tests — `cd backend && pytest`

`ruff check archon tests alembic` clean. No Docker needed for any Phase 13 test.

| Tier | File | Covers |
|---|---|---|
| unit | `tests/unit/test_reporting_workbook.py` | `build_report` on a bare run (snapshot only) still emits 14 sheets and a valid (`PK…`) xlsx |
| integration | `tests/integration/test_reporting_api.py` | `GET /runs/{id}/report.xlsx` → 200, xlsx content-type + `Content-Disposition`, `wb.sheetnames == SHEET_NAMES`; Legacy-DNA / Technical-Debt sheet cells equal the matching JSON endpoints; Executive Summary names the run; 404 on unknown run |
| integration | `tests/integration/test_bulk_import.py` | mixed 3-row workbook → 2 `Repository` + 2 `Job(QUEUED)` with the right `priority`, 1 error row; duplicate row → `skipped`; missing required column → validation error |
| integration | `tests/integration/test_cli.py` | `archon bulk-import` queues a run, `archon report <id> --out` writes a 14-sheet file |

No existing test regressed — the routers were not refactored, so every `test_*_api.py`
response is byte-identical.

## Verified manually

* `python -m pytest tests/unit tests/integration/test_reporting_api.py
  tests/integration/test_bulk_import.py tests/integration/test_cli.py -q` — green.
* `cd frontend && npm run typecheck && npm run build` — clean.
* `openpyxl 3.1.5` + `python-multipart` already resolvable in the dev venv.

## Known limitations / deferred

* **Router de-duplication** (moving `_run_with_snapshot` / `_qn_map` / the inline
  `select`+mapper blocks into one module) is **Phase 15** — `queries.py` calls the
  routers as-is for now, which already satisfies "one data path".
* **Change Impact sheet** lists only the components whose impact was already computed
  on demand (`POST /runs/{id}/change-impact`); it does not force-compute for every
  module.
* Sheet layout is functional (header + rows, autosized columns) — no charts,
  conditional formatting, or a cover page. `Executive Summary` is a key/value sheet.
