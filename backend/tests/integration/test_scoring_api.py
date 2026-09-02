"""Phase 5 scoring API endpoints (spec sections 27-30, 47)."""

from __future__ import annotations


def _completed(client, repo_path, run_worker_once):
    repo = client.post("/repositories", json={"url": str(repo_path)}).json()
    run = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "ANALYSIS_ONLY"}).json()
    run_worker_once()
    got = client.get(f"/runs/{run['id']}").json()
    assert got["state"] == "COMPLETED"
    return got


def test_legacy_dna_endpoint(client, scoring_repo, run_worker_once):
    run = _completed(client, scoring_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/legacy-dna").json()
    assert len(rows) > 0
    assert all("legacy_risk_score" in r and "coverage_is_proxy" in r for r in rows)
    scores = [r["legacy_risk_score"] for r in rows]
    assert scores == sorted(scores, reverse=True)

    filtered = client.get(f"/runs/{run['id']}/legacy-dna?category=LOW").json()
    assert all(r["category"] == "LOW" for r in filtered)


def test_component_legacy_dna_endpoint(client, scoring_repo, run_worker_once):
    run = _completed(client, scoring_repo, run_worker_once)
    sid = run["snapshot_id"]
    pricing = next(
        c for c in client.get(f"/snapshots/{sid}/components?kind=MODULE&q=pricing_engine").json()
        if c["qualified_name"] == "scoring_shop.pricing_engine"
    )
    dna = client.get(f"/components/{pricing['id']}/legacy-dna").json()
    assert dna is not None
    assert dna["category"] in ("HIGH", "CRITICAL")


def test_hotspots_endpoint(client, scoring_repo, run_worker_once):
    run = _completed(client, scoring_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/hotspots").json()
    assert len(rows) > 0
    classifications = {r["classification"] for r in rows}
    assert classifications <= {"STABLE", "WATCH", "RISKY", "CRITICAL"}

    filtered = client.get(f"/runs/{run['id']}/hotspots?classification=STABLE").json()
    assert all(r["classification"] == "STABLE" for r in filtered)


def test_technical_debt_endpoint(client, scoring_repo, run_worker_once):
    run = _completed(client, scoring_repo, run_worker_once)
    rows = client.get(f"/runs/{run['id']}/technical-debt").json()
    assert len(rows) > 0
    categories = {r["category"] for r in rows}
    assert "MAGIC_NUMBER" in categories or "BROAD_EXCEPT" in categories

    filtered = client.get(f"/runs/{run['id']}/technical-debt?severity=HIGH").json()
    assert all(r["severity"] == "HIGH" for r in filtered)


def test_understanding_endpoint(client, scoring_repo, run_worker_once):
    run = _completed(client, scoring_repo, run_worker_once)
    data = client.get(f"/runs/{run['id']}/understanding").json()
    assert 0.0 <= data["overall_score"] <= 100.0
    assert 0.0 <= data["confidence"] <= 1.0
    assert len(data["dimensions"]) == 6


def test_scoring_endpoints_404_on_unknown_run(client):
    assert client.get("/runs/nope/legacy-dna").status_code == 404
    assert client.get("/runs/nope/hotspots").status_code == 404
    assert client.get("/runs/nope/technical-debt").status_code == 404
    assert client.get("/runs/nope/understanding").status_code == 404


def test_understanding_409_before_run_reaches_scoring(client, scoring_repo, run_worker_once):
    repo = client.post("/repositories", json={"url": str(scoring_repo)}).json()
    run = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "INGEST_ONLY"}).json()
    run_worker_once()
    got = client.get(f"/runs/{run['id']}").json()
    assert got["state"] == "COMPLETED"
    resp = client.get(f"/runs/{run['id']}/understanding")
    assert resp.status_code == 409
