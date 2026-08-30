# ARCHON

**AI Software Archaeologist & Self-Healing Legacy Code Platform.**

Given an unfamiliar Python Git/GitHub repository, ARCHON progressively builds an
evidence-backed understanding of the code, scores its risk, generates tests, runs them in
a sandbox, investigates failures, proposes and verifies minimal patches, remembers
incidents, and recommends a safe modernization order.

* Full plan: [`docs/ARCHON_IMPLEMENTATION_PLAN.md`](docs/ARCHON_IMPLEMENTATION_PLAN.md)
* Architecture (living): [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md)
* Status: **Phase 1 complete** — [`docs/PHASE_1_COMPLETION.md`](docs/PHASE_1_COMPLETION.md)

## Quick start (local, SQLite)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e "backend[dev]" ruff   # Windows
# .venv/bin/python  -m pip install -e "backend[dev]" ruff    # POSIX

cd backend
../.venv/Scripts/python -m archon.cli.main db-upgrade
../.venv/Scripts/python -m archon.cli.main analyze https://github.com/psf/requests --wait
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
cd backend && ../.venv/Scripts/python -m pytest        # 63 passing
../.venv/Scripts/python -m ruff check archon tests alembic
```

## Layout

```
backend/    FastAPI + SQLAlchemy + Alembic; the analysis pipeline, providers, worker, CLI
frontend/   Vite + React + TypeScript; screens read only from the real API
docker/     Dockerfile.api, Dockerfile.worker, docker-compose.yml
docs/       plan, architecture, phase completion records
```
