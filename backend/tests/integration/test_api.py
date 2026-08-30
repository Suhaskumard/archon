"""API surface for Phase 1 (spec sections 47, 54)."""

from __future__ import annotations


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_repository_is_idempotent(client):
    body = {"url": "https://github.com/psf/requests"}
    r1 = client.post("/repositories", json=body)
    assert r1.status_code == 201
    repo = r1.json()
    assert repo["provider"] == "GITHUB"
    assert repo["owner"] == "psf" and repo["name"] == "requests"

    r2 = client.post("/repositories", json=body)
    assert r2.status_code == 201
    assert r2.json()["id"] == repo["id"]  # same row, not a duplicate


def test_create_repository_rejects_bad_url(client):
    r = client.post("/repositories", json={"url": "not a repo"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "INVALID_REPOSITORY_URL"
    assert err["suggested_action"]


def test_missing_payload_is_structured_422(client):
    r = client.post("/repositories", json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION"


def test_run_lifecycle_over_http(client, test_repo, run_worker_once):
    repo = client.post("/repositories", json={"url": str(test_repo)}).json()

    r = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "INGEST_ONLY"})
    assert r.status_code == 202
    run = r.json()
    assert run["state"] == "QUEUED"
    assert r.headers["Location"] == f"/runs/{run['id']}"

    run_worker_once()

    got = client.get(f"/runs/{run['id']}")
    assert got.status_code == 200
    data = got.json()
    assert data["state"] == "COMPLETED"
    assert data["last_completed_stage"] == "SNAPSHOTTING"
    assert data["snapshot"]["commit_sha"]
    assert data["snapshot"]["support_level"] == "SUPPORTED"
    assert any(e["classification"] == "FACT" for e in data["evidence"])

    ev = client.get(f"/runs/{run['id']}/evidence")
    assert ev.status_code == 200 and len(ev.json()) >= 2


def test_duplicate_run_conflicts(client, test_repo):
    repo = client.post("/repositories", json={"url": str(test_repo)}).json()
    first = client.post(f"/repositories/{repo['id']}/runs", json={})
    assert first.status_code == 202
    dup = client.post(f"/repositories/{repo['id']}/runs", json={})
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "CONFLICT"


def test_idempotency_key_returns_same_run(client, test_repo):
    repo = client.post("/repositories", json={"url": str(test_repo)}).json()
    headers = {"Idempotency-Key": "abc-123"}
    a = client.post(f"/repositories/{repo['id']}/runs", json={}, headers=headers)
    b = client.post(f"/repositories/{repo['id']}/runs", json={}, headers=headers)
    assert a.json()["id"] == b.json()["id"]


def test_unknown_ids_are_404(client):
    assert client.get("/runs/run_missing").status_code == 404
    assert client.get("/repositories/repo_missing").status_code == 404
    r = client.post("/repositories/repo_missing/runs", json={})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_openapi_document_lists_endpoints(client):
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/repositories" in paths
    assert "/repositories/{repository_id}/runs" in paths
    assert "/runs/{run_id}" in paths
