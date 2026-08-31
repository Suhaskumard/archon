"""Phase 7 execution API endpoints (spec sections 12, 33, 36, 47)."""

from __future__ import annotations


def _completed(client, repo_path, run_worker_once):
    repo = client.post("/repositories", json={"url": str(repo_path)}).json()
    run = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "FULL"}).json()
    run_worker_once()
    got = client.get(f"/runs/{run['id']}").json()
    assert got["state"] == "COMPLETED"
    return got


def test_tests_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/tests").json()
    assert len(rows) == 2
    assert {r["name"] for r in rows} == {
        "tests.test_calculator.test_add", "tests.test_billing.test_line_total",
    }
    assert all(r["kind"] == "EXISTING" for r in rows)


def test_executions_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/executions").json()
    assert len(rows) == 1
    e = rows[0]
    assert e["kind"] == "EXISTING_TESTS"
    assert e["exit_code"] == 0
    assert e["passed"] == 2
    assert e["failed"] == 0
    assert "passed" in e["stdout_preview"] or e["stdout_preview"] != ""
    assert e["stdout_ref"] is not None
    assert e["coverage_ref"] is not None

    filtered = client.get(f"/runs/{run['id']}/executions?kind=EXISTING_TESTS").json()
    assert len(filtered) == 1


def test_executions_404_on_unknown_run(client):
    assert client.get("/runs/nope/executions").status_code == 404
    assert client.get("/runs/nope/tests").status_code == 404
