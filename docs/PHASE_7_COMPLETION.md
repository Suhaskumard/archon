# Phase 7 — Secure Execution / Sandbox — Completion Record

Per the plan's Phase 7 scope (§12, §36) and the per-phase completion gate. Builds on
Phases 1–6. The Docker sandbox and a generic execution engine that runs existing test
suites through it — the security boundary every later phase's untrusted-code execution
(characterization in Phase 8, patch verification in Phase 9) depends on.

## Scope delivered

Four new pipeline stages, reaching the fixed `Stage` order's `EXECUTING` stage for the
first time.

```
… ANALYZING_CHANGE_IMPACT
   ─▶ ANALYZING_TESTS   existing-test discovery from already-extracted Components
   ─▶ CHARACTERIZING    honest stub - deferred to Phase 8 (one Evidence row, no writes)
   ─▶ GENERATING_TESTS  honest stub - deferred to Phase 8 (one Evidence row, no writes)
   ─▶ EXECUTING         run pytest through the Docker sandbox, capture results
```

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Sandbox contract | `archon/sandbox/base.py` | `Sandbox` ABC + frozen `ExecutionSpec`/`ExecutionResult` dataclasses - the seam for a future non-Docker driver. Every security-relevant field defaults from `SandboxSettings`/`RepositoryLimits.max_sandbox_runtime_seconds`. |
| Docker driver | `archon/sandbox/docker_sandbox.py` | Shells out to the `docker` CLI (argument lists, mirroring `gitcli.py`'s safety conventions) - no `docker` SDK dependency. See "Design findings" below for two real Docker behaviours discovered and worked around this phase. |
| Reaper | `archon/sandbox/reaper.py` | `reap_orphan_containers()` - removes anything labeled `archon.managed=true`; called once at worker startup (`jobs/worker.py::Worker._reap_orphans`) alongside `WorkspaceManager.reap_orphans()`, and via `archon reap` CLI. |
| Test discovery | `archon/testing/discovery.py` | `discover_existing_tests` - a test function is identified by: its owning MODULE is flagged `is_test` (Phase 2), and its own name has a `test_` prefix (Phase 2 never sets `is_test` on FUNCTION/METHOD rows themselves). Persists `TestCase(kind=EXISTING, origin=DISCOVERED)`. |
| Execution engine | `archon/execution/runner.py` | `run_existing_tests` - builds one `pytest -q --tb=short --junit-xml=... --cov=. --cov-report=xml:...` `ExecutionSpec`, runs it via `DockerSandbox`, parses pytest's summary line for passed/failed/errors, persists one `Execution(kind=EXISTING_TESTS)` row + stdout/stderr/coverage/junit text artifacts. |
| Artifact storage | `archon/core/artifacts.py` | New `write_text`/`read_text` siblings of `write_json`/`read_json` for non-JSON blobs. |
| Schema | `alembic/versions/0007_execution.py` | `test_cases`, `executions` |
| Enums | `domain/enums.py` | `TestCaseKind`, `TestCaseOrigin`, `ExecutionKind` (`EnumString` - grows every phase like `Dependency.kind`) |
| Pipeline | `archon/pipeline/orchestrator.py` | 4 new stages/dispatch methods; 4 new `PipelineResult` fields |
| API | `archon/api/routers/execution.py` (new file) | `GET /runs/{id}/tests`, `GET /runs/{id}/executions` (capped stdout/stderr preview + artifact refs for the full text) |
| Frontend | `frontend/src/App.tsx`, `api.ts` | Test Execution panel (discovered-test count + a flat execution-result table) |
| Docker image | `docker/Dockerfile.sandbox` | `python:3.12-slim`, non-root `sandboxuser` (uid 1000), `pytest`/`pytest-cov`/`coverage` baked in (ARCHON-side tooling, not the target repo's deps). Built once via `make sandbox-image` - never by the test suite. |
| Fixture | `tests/fixtures/malicious/build_malicious_repo.py` | A non-git, pytest-discoverable directory with one test function per attempted bad behaviour (network, fork bomb, secret read, fs escape) - see "Verified manually" below for actual results. |

## Design findings (discovered empirically this phase, not assumed)

* **`docker cp` cannot see tmpfs-mounted paths at all**, in either direction - it reads
  the storage driver's layer diff, which a tmpfs mount never joins. Writing `docker cp
  <src> <container>:/work` on a `--read-only` container failed with "container rootfs is
  marked read-only" even though `/work` is a writable tmpfs; reading back
  `docker cp <container>:/work/out .` failed with "Could not find the file" despite the
  files genuinely existing (confirmed via `docker exec ls`). **Fix**: both directions
  go through `docker exec` + `tar` over stdin/stdout instead - a process running inside
  the container's own mount namespace sees the tmpfs fine; `docker cp`'s failure is a
  client/daemon-side limitation of the copy mechanism itself, unrelated to actual
  filesystem permissions.
* **`docker cp` also refuses a container that hasn't been started** (tmpfs mounts
  aren't attached until `docker start`) - solved by the same tar-over-exec approach,
  which naturally requires a running container anyway.
* **`--ulimit nproc` is a per-real-UID kernel limit shared across every container using
  that UID on the host**, not a per-container control - on a host already running many
  containers as uid 1000, a low `--ulimit nproc` caused unrelated containers to fail
  with "resource temporarily unavailable" before the fork-bomb test even started.
  **Fix**: dropped `--ulimit nproc` entirely; `--pids-limit` (a genuine per-container
  cgroup control) is the correct and sufficient mechanism, exactly as Docker's own
  security guidance recommends.
* **stdout/stderr from a wall-clock-killed `docker exec`** are lost if captured only
  from the `docker exec` client process (killing the client doesn't retrieve partial
  output). **Fix**: the actual command's stdout/stderr are redirected to files inside
  `/work` by the wrapping shell script, then read back via the tar-over-exec copy-out -
  this survives a timeout-triggered `docker kill` since the files exist independently of
  whether the exec client itself completed normally.

## Tests — `cd backend && pytest`

All prior tests unchanged and green. `ruff check archon tests alembic` clean.

| Tier | Files | Covers |
|---|---|---|
| unit | `test_execution_spec.py` - `ExecutionSpec`/`ExecutionResult` defaults, overrides, frozen-ness | pure dataclass level, no Docker |
| integration | `test_docker_sandbox.py` (12 cases, real Docker, skips cleanly if the daemon/image is missing) - echo/exit-code capture, workspace files copied in, wall-clock timeout + kill, non-root user, read-only rootfs, writable `/work`, network isolation (instant "unreachable", no timeout wait), `--pids-limit` containment of a real bounded fork-bomb attempt, empty-environment secret-leak check, output-file copy-out, container removed after run | |
| acceptance | `test_phase7_sandbox.py` | run reaches `COMPLETED` at `EXECUTING`; `test_repo`'s 2 real pytest tests are discovered, executed, and captured accurately (`exit_code=0, passed=2, failed=0`, stdout/coverage artifacts present); the malicious fixture's 4 attacks are all contained (non-zero exit, no timeout needed) with a fake host secret verified absent from all captured output |

## Verified manually

* Docker Desktop started and confirmed reachable (`docker ps`) before any sandbox code
  was written, per the user's explicit direction to verify this phase with real
  containers rather than stub/skip it.
* `archon-sandbox:latest` built via `make sandbox-image`.
* Every threat-model control verified individually with a real container before being
  combined: plain `echo` → resource-limited `sleep` timeout-kill → network isolation
  alone → fork-bomb alone (bounded to `pids_limit=32`, contained at exactly 29 forked
  processes, completed in ~1.2s) → the full malicious suite together (all 4 attacks
  failed/errored as expected, completed in ~1.7s, a fake `ARCHON_GITHUB_TOKEN` never
  appeared in captured output) → the full pipeline on `test_repo` reaching `EXECUTING`
  with `exit_code=0, passed=2`.
* HTTP: `/runs/{id}/tests` and `/runs/{id}/executions` verified against a live
  `FULL` run.
* Frontend: `npm run build` clean; the Test Execution panel verified rendering real
  data (discovered-test count, exit code, pass/fail counts, duration) against a locally
  completed run via a live backend + frontend dev server.
* No orphaned containers left behind after any test run
  (`docker ps -a --filter label=archon.managed=true` empty).

## Known limitations / deferred

* **The opt-in egress-filtered dependency-install phase is declared, not implemented.**
  `ExecutionSpec.allow_install=True` raises a typed `ArchonError` - no fixture needs
  installed third-party dependencies at sandbox-run time yet.
* **`CHARACTERIZING`/`GENERATING_TESTS` are honest stubs** - each records exactly one
  `INFERENCE` Evidence row noting deferral to Phase 8, with no table writes. Phase 8
  replaces both with real work.
* **Static scanning of generated diffs/tests is Phase 9's job** - nothing is
  AI-generated yet in this phase (only the target repo's own *existing* tests run), so
  there is nothing to scan.
* **coverage.xml/junit.xml are stored as raw text artifacts, not yet parsed** - Phase 8
  parses `coverage.xml` for test-gap analysis; this phase only captures and exposes it.
* **Failure detection/investigation is Phase 9's job** - a non-zero exit code is
  captured and reported, but no root-cause analysis happens yet.
* **The containerized (`docker compose`) worker deployment is updated but not
  full-stack verified this phase.** `docker/Dockerfile.worker` now installs the
  `docker` CLI and `docker/docker-compose.yml`'s worker service now mounts the host's
  `/var/run/docker.sock` (sibling-container access - `DockerSandbox` never bind-mounts
  a host path, since it streams the workspace in/out over `docker exec` + `tar`, so the
  usual Docker-outside-of-Docker path-translation gotcha doesn't apply here). `docker
  compose config` was validated for syntax; the full stack was not brought up and
  exercised end-to-end in this session - only the local (non-containerized) worker path
  was verified against real containers.
