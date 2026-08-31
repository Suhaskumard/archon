"""Phase 8 characterization/test-gap API endpoints (spec sections 33-36, 47)."""

from __future__ import annotations


def _completed(client, repo_path, run_worker_once):
    repo = client.post("/repositories", json={"url": str(repo_path)}).json()
    run = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "FULL"}).json()
    run_worker_once()
    got = client.get(f"/runs/{run['id']}").json()
    assert got["state"] == "COMPLETED"
    return got


def test_characterization_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/characterization").json()
    assert isinstance(rows, list)
    for r in rows:
        assert r["baseline_hash"]
        assert isinstance(r["input_spec"], list)


def test_test_gaps_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/test-gaps").json()
    assert isinstance(rows, list)
    assert rows  # the fixture has a known gap - the list must not be empty
    priorities = {r["priority"] for r in rows}
    assert priorities <= {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    # sorted by priority_score descending
    scores = [r["priority_score"] for r in rows]
    assert scores == sorted(scores, reverse=True)

    reserve_gap = next((r for r in rows if r["component_qn"] and r["component_qn"].endswith("reserve")), None)
    assert reserve_gap is not None
    assert reserve_gap["kind"] == "UNTESTED_FUNCTION"

    filtered = client.get(f"/runs/{run['id']}/test-gaps?priority={reserve_gap['priority']}").json()
    assert all(r["priority"] == reserve_gap["priority"] for r in filtered)


def test_characterization_and_gaps_404_on_unknown_run(client):
    assert client.get("/runs/nope/characterization").status_code == 404
    assert client.get("/runs/nope/test-gaps").status_code == 404
