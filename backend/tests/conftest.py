from __future__ import annotations

import os
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

    from archon.api.deps import reset_rate_limiters
    from archon.core.observability import reset_metrics
    from archon.db.migrate import upgrade

    reset_metrics()
    reset_rate_limiters()
    upgrade()
    yield
    db_base.reset_engine_cache()
    config.reset_settings_cache()
    reset_rate_limiters()


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
def polyglot_repo(tmp_path_factory) -> Path:
    from tests.fixtures.build_polyglot_repo import build_polyglot_repo

    return build_polyglot_repo(tmp_path_factory.mktemp("polyglot_fixture_repo"))


@pytest.fixture
def malicious_repo(tmp_path_factory) -> Path:
    from tests.fixtures.malicious.build_malicious_repo import build_malicious_repo

    dest = tmp_path_factory.mktemp("malicious_fixture")
    return build_malicious_repo(dest)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from archon.api.app import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="session")
def sandbox_image_available() -> bool:
    """Skip Docker-dependent tests with a clear message if the daemon or the
    ``archon-sandbox`` image isn't available - the image is built once by hand
    (``make sandbox-image``), never by the test suite itself."""
    import subprocess

    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", "archon-sandbox:latest"],
            capture_output=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("docker is not available")
    if proc.returncode != 0:
        pytest.skip("archon-sandbox:latest image not built - run `make sandbox-image`")
    return True


@pytest.fixture(scope="session")
def anthropic_api_key_available() -> str:
    """Skip live Claude-provider tests unless a real key AND the SDK are present -
    mirrors ``sandbox_image_available`` for the Docker tests."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set - live Claude provider test skipped")
    pytest.importorskip("anthropic", reason="run: pip install -e 'backend[claude]'")
    return key


@pytest.fixture
def sandbox_workspace(sandbox_image_available):
    """A throwaway Workspace with an empty `repo/` dir, for sandbox tests that don't
    need a real git checkout - just something to copy in."""
    from archon.workspace.manager import WorkspaceManager

    wm = WorkspaceManager()
    ws = wm.create("sbtest")
    ws.resolve_within("repo").mkdir(parents=True, exist_ok=True)
    yield ws
    wm.cleanup(ws)


@pytest.fixture
def run_worker_once():
    from archon.jobs.worker import Worker

    def _run(max_ticks: int = 10) -> None:
        w = Worker()
        for _ in range(max_ticks):
            if not w.tick():
                break

    return _run
