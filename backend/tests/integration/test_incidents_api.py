"""Phase 10 incident memory API endpoints (spec sections 44, 47)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _needs_sandbox(sandbox_image_available):
    """Every test here drives a FULL run through EXECUTING - skip cleanly without Docker."""


def _completed(client, repo_path, run_worker_once):
    repo = client.post("/repositories", json={"url": str(repo_path)}).json()
    run = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "FULL"}).json()
    run_worker_once(max_ticks=60)
    got = client.get(f"/runs/{run['id']}").json()
    assert got["state"] == "COMPLETED"
    return got, repo


def test_run_incidents_endpoint(client, test_repo, run_worker_once):
    run, _repo = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/incidents").json()
    assert len(rows) == 1
    inc = rows[0]
    assert inc["run_id"] == run["id"]
    assert inc["failure_signature"]
    assert inc["patch_id"]
    assert inc["fix_ref"]


def test_repository_incidents_endpoint(client, test_repo, run_worker_once):
    run, repo = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/repositories/{repo['id']}/incidents").json()
    assert len(rows) == 1
    assert rows[0]["repo_id"] == repo["id"]


def test_incidents_endpoints_404_on_unknown_ids(client):
    assert client.get("/runs/nope/incidents").status_code == 404
    assert client.get("/repositories/nope/incidents").status_code == 404
