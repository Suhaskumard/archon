"""Phase 6 change safety / change impact API endpoints (spec sections 31-32, 47)."""

from __future__ import annotations


def _completed(client, repo_path, run_worker_once):
    repo = client.post("/repositories", json={"url": str(repo_path)}).json()
    run = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "ANALYSIS_ONLY"}).json()
    run_worker_once()
    got = client.get(f"/runs/{run['id']}").json()
    assert got["state"] == "COMPLETED"
    return got


def test_change_safety_endpoint(client, scoring_repo, run_worker_once):
    run = _completed(client, scoring_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/change-safety").json()
    assert len(rows) > 0
    assert all("safety_score" in r and "recommended_preparation" in r for r in rows)
    scores = [r["safety_score"] for r in rows]
    assert scores == sorted(scores)  # ascending: least-safe first

    filtered = client.get(f"/runs/{run['id']}/change-safety?risk_category=SAFE").json()
    assert all(r["risk_category"] == "SAFE" for r in filtered)


def test_change_safety_404_on_unknown_run(client):
    assert client.get("/runs/nope/change-safety").status_code == 404


def test_change_impact_for_precomputed_module_returns_instantly(client, scoring_repo, run_worker_once):
    run = _completed(client, scoring_repo, run_worker_once)
    sid = run["snapshot_id"]
    pricing = next(
        c for c in client.get(f"/snapshots/{sid}/components?kind=MODULE&q=pricing_engine").json()
        if c["qualified_name"] == "scoring_shop.pricing_engine"
    )
    resp = client.post(f"/runs/{run['id']}/change-impact", json={"component_id": pricing["id"]})
    assert resp.status_code == 200
    data = resp.json()
    dependents = {d["qualified_name"] for d in data["direct_dependents"]} | {
        d["qualified_name"] for d in data["indirect_dependents"]
    }
    assert dependents & {
        "scoring_shop.checkout", "scoring_shop.invoice", "scoring_shop.promotions",
        "scoring_shop.discount_rules",
    }


def test_change_impact_for_uncomputed_function_computes_and_upserts(client, scoring_repo, run_worker_once):
    run = _completed(client, scoring_repo, run_worker_once)
    sid = run["snapshot_id"]
    fn = next(
        c for c in client.get(f"/snapshots/{sid}/components?kind=FUNCTION&q=price_for").json()
        if c["qualified_name"] == "scoring_shop.pricing_engine.price_for"
    )
    first = client.post(f"/runs/{run['id']}/change-impact", json={"component_id": fn["id"]})
    assert first.status_code == 200
    second = client.post(f"/runs/{run['id']}/change-impact", json={"component_id": fn["id"]})
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_change_impact_404_on_unknown_component(client, scoring_repo, run_worker_once):
    run = _completed(client, scoring_repo, run_worker_once)
    resp = client.post(f"/runs/{run['id']}/change-impact", json={"component_id": "nope"})
    assert resp.status_code == 404


def test_change_impact_404_on_unknown_run(client):
    resp = client.post("/runs/nope/change-impact", json={"component_id": "nope"})
    assert resp.status_code == 404


def test_change_impact_409_before_run_has_snapshot(client, scoring_repo):
    repo = client.post("/repositories", json={"url": str(scoring_repo)}).json()
    run = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "INGEST_ONLY"}).json()
    resp = client.post(f"/runs/{run['id']}/change-impact", json={"component_id": "nope"})
    assert resp.status_code == 409
