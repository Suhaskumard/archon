"""Archaeology API endpoints (spec sections 24-26, 47)."""

from __future__ import annotations


def _completed(client, test_repo, run_worker_once):
    repo = client.post("/repositories", json={"url": str(test_repo)}).json()
    run = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "ANALYSIS_ONLY"}).json()
    run_worker_once()
    got = client.get(f"/runs/{run['id']}").json()
    assert got["state"] == "COMPLETED"
    return got


def test_evolution_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    evo = client.get(f"/runs/{run['id']}/evolution").json()
    assert evo["analyzed_commits"] == 3
    assert evo["authors"] == 1
    assert evo["span_days"] > 0
    assert len(evo["timeline"]) >= 1
    churn_paths = {c["qualified_name"] for c in evo["top_churn"]}
    assert "legacy_shop.billing" in churn_paths
    pairs = {frozenset({c["a"], c["b"]}) for c in evo["top_co_change"]}
    assert frozenset({"legacy_shop.billing", "legacy_shop.calculator"}) in pairs


def test_commits_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    sid = run["snapshot_id"]
    commits = client.get(f"/snapshots/{sid}/commits").json()
    assert len(commits) == 3
    assert all(c["author_email"] == "fixture@archon.test" for c in commits)
    filtered = client.get(f"/snapshots/{sid}/commits?author=nobody").json()
    assert filtered == []


def test_component_history_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    sid = run["snapshot_id"]
    billing = next(
        c for c in client.get(f"/snapshots/{sid}/components?kind=MODULE&q=legacy_shop.billing").json()
        if c["qualified_name"] == "legacy_shop.billing"
    )
    hist = client.get(f"/components/{billing['id']}/history").json()
    assert hist["git"]["commit_count"] == 2
    assert len(hist["commits"]) == 2
    neigh = {n["qualified_name"] for n in hist["co_changed_with"]}
    assert "legacy_shop.calculator" in neigh


def test_assumptions_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/assumptions").json()
    assert len(rows) >= 3
    assert {r["kind"] for r in rows} >= {"division", "global_state"}
    # sorted by risk (HIGH first)
    ranks = ["HIGH", "MEDIUM", "LOW"]
    idxs = [ranks.index(r["risk"]) for r in rows]
    assert idxs == sorted(idxs)
    div = client.get(f"/runs/{run['id']}/assumptions?kind=division").json()
    assert div and all(r["kind"] == "division" for r in div)
    high = client.get(f"/runs/{run['id']}/assumptions?risk=high").json()
    assert all(r["risk"] == "HIGH" for r in high)


def test_behavior_endpoints(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/behavior").json()
    assert len(rows) >= 8
    reserve = next(r for r in rows if r["component_qn"] == "legacy_shop.inventory.reserve")
    assert "ValueError" in (reserve["exceptions"] or [])
    assert reserve["purpose"]

    one = client.get(f"/components/{reserve['component_id']}/behavior").json()
    assert one["component_qn"] == "legacy_shop.inventory.reserve"


def test_archaeology_404_409(client, test_repo, run_worker_once):
    assert client.get("/runs/run_missing/evolution").status_code == 404
    assert client.get("/snapshots/snap_missing/commits").status_code == 404
    assert client.get("/components/comp_missing/history").status_code == 404
    repo = client.post("/repositories", json={"url": str(test_repo)}).json()
    run = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "INGEST_ONLY"}).json()
    run_worker_once()
    r = client.get(f"/runs/{run['id']}/evolution")
    assert r.status_code == 409
