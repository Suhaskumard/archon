"""POST /webhooks/github end to end (Phase 19, spec section 51)."""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess

import pytest

from archon.config import reset_settings_cache
from archon.db.base import session_scope
from archon.db.models import AnalysisRun, WebhookDelivery
from archon.domain.enums import Stage

SECRET = "webhook-test-secret"


def _head_sha(repo_path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_path), capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture(autouse=True)
def _webhook_secret(monkeypatch):
    monkeypatch.setenv("ARCHON_GITHUB_WEBHOOK_SECRET", SECRET)
    reset_settings_cache()
    yield
    monkeypatch.delenv("ARCHON_GITHUB_WEBHOOK_SECRET", raising=False)
    reset_settings_cache()


def _push_body(repo_url: str, *, after="a" * 40, changed=("legacy_shop/calculator.py",)) -> bytes:
    payload = {
        "ref": "refs/heads/main",
        "before": "b" * 40,
        "after": after,
        "repository": {"full_name": "acme/widgets", "html_url": repo_url},
        "commits": [{"added": [], "modified": list(changed), "removed": []}],
    }
    return json.dumps(payload).encode()


def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _headers(body: bytes, *, delivery="d-1", event="push", sign=True) -> dict:
    h = {"X-GitHub-Event": event, "X-GitHub-Delivery": delivery, "Content-Type": "application/json"}
    if sign:
        h["X-Hub-Signature-256"] = _sig(body)
    return h


def _register_repo(client, test_repo) -> dict:
    return client.post("/repositories", json={"url": str(test_repo)}).json()


def test_signed_push_queues_incremental_run(client, test_repo):
    repo = _register_repo(client, test_repo)
    body = _push_body(repo["url"])
    r = client.post("/webhooks/github", content=body, headers=_headers(body))
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "queued"
    assert data["mode"] == "INCREMENTAL"
    assert r.headers["Location"] == f"/runs/{data['run_id']}"

    run = client.get(f"/runs/{data['run_id']}").json()
    assert run["mode"] == "INCREMENTAL"
    assert run["trigger"]["source"] == "webhook"
    assert run["trigger"]["sha"] == "a" * 40

    with session_scope() as session:
        d = session.query(WebhookDelivery).filter_by(delivery_id="d-1").one()
        assert d.status == "queued"
        assert d.run_id == data["run_id"]
        assert d.changed_paths == ["legacy_shop/calculator.py"]
        stored = session.get(AnalysisRun, data["run_id"])
        assert stored.changed_paths == ["legacy_shop/calculator.py"]


def test_bad_signature_rejected(client, test_repo):
    repo = _register_repo(client, test_repo)
    body = _push_body(repo["url"])
    h = _headers(body)
    h["X-Hub-Signature-256"] = "sha256=" + "0" * 64
    r = client.post("/webhooks/github", content=body, headers=h)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"
    with session_scope() as session:
        assert session.query(AnalysisRun).count() == 0
        assert session.query(WebhookDelivery).count() == 0


def test_replayed_delivery_conflicts(client, test_repo):
    repo = _register_repo(client, test_repo)
    body = _push_body(repo["url"])
    first = client.post("/webhooks/github", content=body, headers=_headers(body))
    assert first.status_code == 202
    second = client.post("/webhooks/github", content=body, headers=_headers(body))
    assert second.status_code == 409
    with session_scope() as session:
        assert session.query(AnalysisRun).count() == 1


def test_non_push_event_ignored(client, test_repo):
    repo = _register_repo(client, test_repo)
    body = _push_body(repo["url"])
    r = client.post("/webhooks/github", content=body, headers=_headers(body, event="ping"))
    assert r.status_code == 202
    assert r.json()["status"] == "ignored"
    with session_scope() as session:
        assert session.query(AnalysisRun).count() == 0
        assert session.query(WebhookDelivery).filter_by(status="ignored_event").count() == 1


def test_unknown_repo_ignored(client, test_repo):
    body = _push_body("https://github.com/nobody/unregistered")
    r = client.post("/webhooks/github", content=body, headers=_headers(body))
    assert r.status_code == 202
    assert r.json()["status"] == "ignored"
    with session_scope() as session:
        assert session.query(WebhookDelivery).filter_by(status="ignored_no_repo").count() == 1


def test_no_file_changes_ignored(client, test_repo):
    repo = _register_repo(client, test_repo)
    body = _push_body(repo["url"], changed=())
    r = client.post("/webhooks/github", content=body, headers=_headers(body))
    assert r.status_code == 202
    assert r.json()["status"] == "ignored"


def test_incremental_run_completes_at_analyzing_tests(client, test_repo, run_worker_once):
    repo = _register_repo(client, test_repo)
    body = _push_body(repo["url"], after=_head_sha(test_repo))
    run_id = client.post("/webhooks/github", content=body, headers=_headers(body)).json()["run_id"]

    run_worker_once(max_ticks=20)

    run = client.get(f"/runs/{run_id}").json()
    assert run["state"] == "COMPLETED"
    assert run["last_completed_stage"] == Stage.ANALYZING_TESTS.value

    ev = client.get(f"/runs/{run_id}/evidence").json()
    produced_by = {e["produced_by"] for e in ev}
    assert "incremental.v1" in produced_by
    assert not any(p.startswith("claude:") for p in produced_by)  # mock default, no AI stage

    with session_scope() as session:
        stored = session.get(AnalysisRun, run_id)
        assert set(stored.engine_versions) >= {"incremental"}
