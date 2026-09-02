# ARCHON

**AI Software Archaeologist & Self-Healing Legacy Code Platform.**

Given an unfamiliar Python Git/GitHub repository, ARCHON progressively builds an
evidence-backed understanding of the code, scores its risk, generates tests, runs them in
a sandbox, investigates failures, proposes and verifies minimal patches, remembers
incidents, and recommends a safe modernization order.

* Full plan: `docs/ARCHON_IMPLEMENTATION_PLAN.pdf` · continuation: [`docs/ROADMAP.md`](docs/ROADMAP.md) (Phases 13–18: hardening & completion)
* Architecture (living): [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md)
* Status: **All 12 spec phases complete** — the closed loop (ingest → analyse → score →
  characterize → execute → investigate → patch → verify → record incident →
  modernize) runs end to end. Phases 13–18 (reporting, test/CI hardening, de-duplication,
  scoring calibration, frontend modernization, real Claude driver + webhook) are in
  progress — see [`docs/ROADMAP.md`](docs/ROADMAP.md). —
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
  [Phase 13](docs/PHASE_13_COMPLETION.md) (Excel reporting & bulk input)

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

Frontend:

```bash
cd frontend && npm install && npm run dev           # http://127.0.0.1:5173 (proxies to :8000)
```

Full stack in containers:

```bash
docker compose -f docker/docker-compose.yml up --build
```

## Tests

```bash
make sandbox-image                                     # build the Docker sandbox image once (Phase 7)
cd backend && ../.venv/Scripts/python -m pytest        # 284 passing (sandbox tests skip cleanly if Docker/the image is missing)
../.venv/Scripts/python -m ruff check archon tests alembic
```

## Layout

```
backend/    FastAPI + SQLAlchemy + Alembic; the analysis pipeline, providers, worker, CLI
frontend/   Vite + React + TypeScript; screens read only from the real API
docker/     Dockerfile.api, Dockerfile.worker, docker-compose.yml
docs/       plan, architecture, phase completion records
```
