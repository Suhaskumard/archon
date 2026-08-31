"""Phase 9 failure investigation & self-healing API endpoints (spec sections 37-43, 47)."""

from __future__ import annotations


def _completed(client, repo_path, run_worker_once):
    repo = client.post("/repositories", json={"url": str(repo_path)}).json()
    run = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "FULL"}).json()
    run_worker_once(max_ticks=60)
    got = client.get(f"/runs/{run['id']}").json()
    assert got["state"] == "COMPLETED"
    return got


def test_failures_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/failures").json()
    assert len(rows) == 1
    f = rows[0]
    assert f["test_identifier"] == "tests.test_calculator.test_divide_by_zero_returns_none"
    assert f["exception_type"] == "ZeroDivisionError"
    assert f["reproducible"] is True
    assert any(fr["component_id"] for fr in f["parsed_frames"])


def test_investigations_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/investigations").json()
    assert len(rows) == 1
    inv = rows[0]
    assert inv["confidence"] >= 0.6
    assert inv["root_cause_hypotheses"]
    assert "division" in inv["summary"].lower()


def test_patches_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/patches").json()
    assert len(rows) == 2
    strategies = {p["strategy"] for p in rows}
    assert strategies == {"guard_zero_divisor", "naive_integer_division"}
    assert all(p["diff_ref"] for p in rows)
    assert all(p["diff_preview"] for p in rows)
    # sorted by rank_score desc
    scores = [p["rank_score"] for p in rows]
    assert scores == sorted(scores, reverse=True)

    verified = client.get(f"/runs/{run['id']}/patches?state=VERIFIED").json()
    assert len(verified) == 1
    assert verified[0]["strategy"] == "guard_zero_divisor"


def test_verifications_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/verifications").json()
    assert len(rows) == 2
    verdicts = {r["verdict"] for r in rows}
    assert verdicts == {"VERIFIED", "REJECTED"}
    verified = next(r for r in rows if r["verdict"] == "VERIFIED")
    assert verified["original_failure_fixed"] is True
    assert verified["applies_cleanly"] is True


def test_healing_endpoints_404_on_unknown_run(client):
    for path in ("failures", "investigations", "patches", "verifications"):
        assert client.get(f"/runs/nope/{path}").status_code == 404
