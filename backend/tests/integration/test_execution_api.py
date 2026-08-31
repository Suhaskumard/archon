"""Phase 7-8 execution API endpoints (spec sections 12, 33-36, 47)."""

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
    # Phase 8 adds characterization + AI-generated TestCase rows on top of the 3
    # existing ones discovered by Phase 7 (Phase 9 plants a genuinely-failing test,
    # test_divide_by_zero_returns_none - discovery finds it regardless of pass/fail).
    existing = [r for r in rows if r["kind"] == "EXISTING"]
    assert {r["name"] for r in existing} == {
        "tests.test_calculator.test_add", "tests.test_billing.test_line_total",
        "tests.test_calculator.test_divide_by_zero_returns_none",
    }
    assert len(rows) > len(existing)  # Phase 8 characterization/AI rows are present too

    filtered = client.get(f"/runs/{run['id']}/tests?kind=EXISTING").json()
    assert len(filtered) == 3


def test_executions_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/executions").json()
    # Phase 8 adds one Execution row per characterization/AI-generation target on top
    # of Phase 7's single EXISTING_TESTS row for this run.
    filtered = client.get(f"/runs/{run['id']}/executions?kind=EXISTING_TESTS").json()
    assert len(filtered) == 1
    e = filtered[0]
    assert e["kind"] == "EXISTING_TESTS"
    assert e["exit_code"] != 0  # the planted failure (Phase 9) makes the suite fail
    assert e["passed"] >= 2
    assert e["failed"] == 1
    assert "passed" in e["stdout_preview"] or e["stdout_preview"] != ""
    assert e["stdout_ref"] is not None
    assert e["coverage_ref"] is not None
    assert len(rows) >= len(filtered)


def test_executions_404_on_unknown_run(client):
    assert client.get("/runs/nope/executions").status_code == 404
    assert client.get("/runs/nope/tests").status_code == 404
