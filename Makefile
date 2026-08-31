# ARCHON developer tasks. Run from the repo root.
PY ?= .venv/Scripts/python.exe
BACKEND := backend

.PHONY: help venv install migrate test lint run-api run-worker analyze e2e clean sandbox-image

help:
	@echo "venv          - create .venv"
	@echo "install       - install backend (editable) + dev deps"
	@echo "migrate       - alembic upgrade head"
	@echo "test          - run the backend test suite"
	@echo "lint          - ruff check"
	@echo "run-api       - start the FastAPI app on :8000"
	@echo "run-worker    - start the analysis worker"
	@echo "analyze R=    - headless: ingest repo/path R end-to-end"
	@echo "e2e           - run the acceptance suite only"
	@echo "sandbox-image - build the archon-sandbox Docker image (required before Phase 7 sandbox tests run)"

venv:
	python -m venv .venv

install:
	$(PY) -m pip install -U pip
	$(PY) -m pip install -e "./$(BACKEND)[dev]" ruff

migrate:
	cd $(BACKEND) && ../$(PY) -m archon.cli.main db-upgrade

test:
	cd $(BACKEND) && ../$(PY) -m pytest

e2e:
	cd $(BACKEND) && ../$(PY) -m pytest tests/acceptance -q

lint:
	cd $(BACKEND) && ../$(PY) -m ruff check archon tests alembic

run-api:
	cd $(BACKEND) && ../$(PY) -m archon.cli.main serve --host 0.0.0.0 --port 8000

run-worker:
	cd $(BACKEND) && ../$(PY) -m archon.cli.main worker

analyze:
	cd $(BACKEND) && ../$(PY) -m archon.cli.main analyze "$(R)"

sandbox-image:
	docker build -f docker/Dockerfile.sandbox -t archon-sandbox:latest .

clean:
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/_archon_data $(BACKEND)/archon.db _archon_data
	find $(BACKEND) -name __pycache__ -type d -exec rm -rf {} +
