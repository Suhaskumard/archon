"""/metrics, /readyz, /admin/runs + abuse controls (Phase 20, spec sections 16, 55)."""

from __future__ import annotations

from archon.config import reset_settings_cache


def test_metrics_scrapes_cleanly(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    body = r.text
    for series in (
        "archon_stage_duration_seconds",
        "archon_run_outcomes_total",
        "archon_jobs_queued",
        "archon_ai_calls_total",
        "archon_http_requests_total",
    ):
        assert series in body


def test_readyz_is_ready_on_a_migrated_db(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
    assert r.json()["revision"]


def test_admin_runs_reports_operational_rows(client, test_repo, run_worker_once):
    repo = client.post("/repositories", json={"url": str(test_repo)}).json()
    run = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "INGEST_ONLY"}).json()
    run_worker_once()

    r = client.get("/admin/runs")
    assert r.status_code == 200
    data = r.json()
    row = next(x for x in data["runs"] if x["run_id"] == run["id"])
    assert row["state"] == "COMPLETED"
    assert row["mode"] == "INGEST_ONLY"
    assert row["repository"] == repo["url"]
    assert row["duration_seconds"] is not None
    assert row["trigger"] == "api"

    r2 = client.get("/admin/runs", params={"state": "FAILED"})
    assert all(x["state"] == "FAILED" for x in r2.json()["runs"])


def test_run_creation_is_rate_limited(client, test_repo, monkeypatch):
    monkeypatch.setenv("ARCHON_RATE_LIMIT_RUNS_PER_MINUTE", "2")
    reset_settings_cache()
    from archon.api.deps import reset_rate_limiters

    reset_rate_limiters()
    repo = client.post("/repositories", json={"url": str(test_repo)}).json()

    ok1 = client.post(f"/repositories/{repo['id']}/runs",
                      json={"ref": "a", "mode": "INGEST_ONLY"})
    ok2 = client.post(f"/repositories/{repo['id']}/runs",
                      json={"ref": "b", "mode": "INGEST_ONLY"})
    blocked = client.post(f"/repositories/{repo['id']}/runs",
                          json={"ref": "c", "mode": "INGEST_ONLY"})
    assert ok1.status_code == 202 and ok2.status_code == 202
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"


def test_oversized_request_body_is_rejected(client, monkeypatch):
    monkeypatch.setenv("ARCHON_MAX_REQUEST_BYTES", "200")
    reset_settings_cache()
    big = {"url": "x" * 500}
    r = client.post("/repositories", json=big)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "REQUEST_TOO_LARGE"


def test_metrics_endpoint_itself_is_not_counted(client):
    client.get("/metrics")
    body = client.get("/metrics").text
    assert 'route="/metrics"' not in body
