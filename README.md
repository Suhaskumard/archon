# ARCHON

**AI Software Archaeologist & Self-Healing Legacy Code Platform.**

Given an unfamiliar Python Git/GitHub repository, ARCHON progressively builds an
evidence-backed understanding of the code, scores its risk, generates tests, runs them in
a sandbox, investigates failures, proposes and verifies minimal patches, remembers
incidents, and recommends a safe modernization order.

* Full plan: `docs/ARCHON_IMPLEMENTATION_PLAN.pdf` · continuation: [`docs/ROADMAP.md`](docs/ROADMAP.md) (Phases 13–20: hardening & completion)
* Architecture (living): [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md)
* Status: **All 12 spec phases complete** — the closed loop (ingest → analyse → score →
  characterize → execute → investigate → patch → verify → record incident →
  modernize) runs end to end. Phases 13–20 (reporting, test/CI hardening, de-duplication,
  scoring calibration, frontend modernization, real Claude driver + push webhook,
  observability & operability) are complete — see [`docs/ROADMAP.md`](docs/ROADMAP.md). —
  [Phase 1](docs/PHASE_1_COMPLETION.md) (ingestion) ·
  [Phase 2](docs/PHASE_2_COMPLETION.md) (source intelligence) ·
  [Phase 3](docs/PHASE_3_COMPLETION.md) (architecture & dependency graph) ·
  [Phase 4](docs/PHASE_4_COMPLETION.md) (git archaeology, hidden assumptions, mock AI) ·
  [Phase 5](docs/PHASE_5_COMPLETION.md) (legacy risk, hotspots, tech debt, repository understanding) ·
  [Phase 6](docs/PHASE_6_COMPLETION.md) (change safety, change impact) ·
  [Phase 7](docs/PHASE_7_COMPLETION.md) (Docker sandbox, secure test execution) ·
  [Phase 8](docs/PHASE_8_COMPLETION.md) (characterization, AI test generation, test-gap analysis) ·
  [Phase 9](docs/PHASE_9_COMPLETION.md) (failure investigation & self-healing) ·
  [Phase 10](docs/PHASE_10_COMPLETION.md) (incident memory) ·
  [Phase 11](docs/PHASE_11_COMPLETION.md) (repository comparison) ·
  [Phase 12](docs/PHASE_12_COMPLETION.md) (modernization) ·
  [Phase 13](docs/PHASE_13_COMPLETION.md) (Excel reporting & bulk input) ·
  [Phase 14](docs/PHASE_14_COMPLETION.md) (test & CI hardening — Docker-free analysis, e2e, schema-drift, property tests) ·
  [Phase 15](docs/PHASE_15_COMPLETION.md) (core de-duplication — scoring `_base`, `enum_value`, redaction breadth) ·
  [Phase 16](docs/PHASE_16_COMPLETION.md) (scoring calibration — measured coverage → `legacy_risk.v2`, `understanding.v2`, calibration test) ·
  [Phase 17](docs/PHASE_17_COMPLETION.md) (frontend architecture — `lib`/`components`/`panels`/`routes`, HashRouter, design tokens) ·
  [Phase 18](docs/PHASE_18_COMPLETION.md) (frontend tests — Vitest + a11y/axe + coverage gate, panel states, zoom/pan module graph) ·
  [Phase 19](docs/PHASE_19_COMPLETION.md) (real `ClaudeAIProvider` + GitHub push webhook → `RunMode.INCREMENTAL`) ·
  [Phase 20](docs/PHASE_20_COMPLETION.md) (observability & operability — Prometheus `/metrics`, `/admin/runs` ops view, hardened prod compose, multi-language contract, rate limits, `perf` tier)

## Quick start (local, SQLite)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e "backend[dev]" ruff   # Windows
# .venv/bin/python  -m pip install -e "backend[dev]" ruff    # POSIX

cd backend
../.venv/Scripts/python -m archon.cli.main db-upgrade
# ingest + Python source analysis (components, dependencies, complexity, entry points)
# ingest + source analysis + architecture reconstruction (roles, dependency graph, cycles)
../.venv/Scripts/python -m archon.cli.main analyze https://github.com/psf/requests --mode full --wait
```

Run the service + worker:

```bash
../.venv/Scripts/python -m archon.cli.main serve    # http://127.0.0.1:8000  (/docs for OpenAPI)
../.venv/Scripts/python -m archon.cli.main worker   # in another terminal
```

Optional — the real Claude AI provider and the GitHub push webhook:

```bash
.venv/Scripts/python -m pip install -e "backend[claude]"   # adds the anthropic SDK
export ANTHROPIC_API_KEY=sk-ant-...        # or set in .env
export ARCHON_AI_PROVIDER=claude           # default is "mock" (offline, deterministic)
export ARCHON_GITHUB_WEBHOOK_SECRET=...    # then POST push events to /webhooks/github
```

A signed `push` webhook enqueues a sandbox-free `RunMode.INCREMENTAL` run scoped to the
changed files; the run view shows a "triggered by push `<sha>`" badge.

Frontend:

```bash
cd frontend && npm install && npm run dev           # http://127.0.0.1:5173 (proxies to :8000)
# componentised React SPA (src/lib · src/components · src/panels · src/routes); HashRouter
# routes #/ (repositories) · #/runs/:id (run view, polls) · #/runs/:id/compare — all deep-linkable
npm run typecheck && npm run test:cov && npm run build   # the CI gate's frontend leg (Vitest + axe + 80% coverage)
```

Full stack in containers:

```bash
docker compose -f docker/docker-compose.yml up --build                       # local dev stack
cp .env.prod.example .env.prod  # set POSTGRES_PASSWORD etc.
docker compose -f docker/docker-compose.prod.yml --env-file .env.prod up -d  # hardened: non-root, healthchecks, limits
```

Observability: `GET /metrics` (Prometheus), `GET /readyz` (DB + migrations), `GET /admin/runs`
(ops view), and the `#/ops` screen in the SPA.

## Tests

```bash
cd backend && ../.venv/Scripts/python -m pytest        # runs with no Docker: analysis suite passes, sandbox/perf tests skip cleanly
make sandbox-image                                     # build the Docker sandbox image once (Phase 7) to also run execution/healing/e2e tests
make perf                                              # perf/concurrency/caching tier (pytest -m perf; deselected by default)
../.venv/Scripts/python -m ruff check archon tests alembic
make ci                                                # lint + backend tests + frontend typecheck/build (the CI gate)
```

## Layout

```
backend/    FastAPI + SQLAlchemy + Alembic; the analysis pipeline, providers, worker, CLI
frontend/   Vite + React + TypeScript; screens read only from the real API
docker/     Dockerfile.api, Dockerfile.worker, docker-compose.yml
docs/       plan, architecture, phase completion records
```
