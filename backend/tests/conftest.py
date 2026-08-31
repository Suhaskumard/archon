from __future__ import annotations

from pathlib import Path

import pytest

_FIXTURES = Path(__file__).parent / "fixtures"


def terminal_stage(mode: str = "FULL"):
    """The last stage the pipeline executes for ``mode`` - use instead of pinning a
    literal stage so adding a later phase does not ripple through every test."""
    from archon.domain.enums import RunMode
    from archon.pipeline.orchestrator import _STAGE_PLANS

    return _STAGE_PLANS[RunMode(mode)][-1]


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Point every test at a throwaway SQLite DB + data root, and migrate it."""
    db_path = tmp_path / "archon.db"
    data_root = tmp_path / "data"
    monkeypatch.setenv("ARCHON_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("ARCHON_DATA_ROOT", str(data_root))
    monkeypatch.setenv("ARCHON_ENVIRONMENT", "test")
    monkeypatch.setenv("ARCHON_LOG_LEVEL", "WARNING")
    monkeypatch.delenv("ARCHON_GITHUB_TOKEN", raising=False)

    import archon.config as config
    import archon.db.base as db_base

    config.reset_settings_cache()
    db_base.reset_engine_cache()
    config.get_settings().ensure_dirs()

    from archon.db.migrate import upgrade

    upgrade()
    yield
    db_base.reset_engine_cache()
    config.reset_settings_cache()


@pytest.fixture
def test_repo(tmp_path_factory) -> Path:
    from tests.fixtures.build_test_repo import build_test_repo

    dest = tmp_path_factory.mktemp("fixture_repo")
    return build_test_repo(dest)


@pytest.fixture
def scoring_repo(tmp_path_factory) -> Path:
    from tests.fixtures.build_scoring_repo import build_scoring_repo

    dest = tmp_path_factory.mktemp("scoring_fixture_repo")
    return build_scoring_repo(dest)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from archon.api.app import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def run_worker_once():
    from archon.jobs.worker import Worker

    def _run(max_ticks: int = 10) -> None:
        w = Worker()
        for _ in range(max_ticks):
            if not w.tick():
                break

    return _run
