"""Architecture API endpoints (spec sections 23, 47)."""

from __future__ import annotations


def _completed(client, test_repo, run_worker_once):
    repo = client.post("/repositories", json={"url": str(test_repo)}).json()
    run = client.post(
        f"/repositories/{repo['id']}/runs", json={"mode": "ANALYSIS_ONLY"}
    ).json()
    run_worker_once()
    got = client.get(f"/runs/{run['id']}").json()
    assert got["state"] == "COMPLETED"
    return got


def test_run_architecture_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    arch = client.get(f"/runs/{run['id']}/architecture").json()

    assert arch["reconstructed"] is True
    assert arch["roles"] == {"domain": 3, "model": 1, "test": 3, "unknown": 1}
    assert arch["cycles"] == []
    assert arch["layering_violations"] == []

    mods = {m["qualified_name"]: m for m in arch["modules"]}
    assert mods["legacy_shop.billing"]["role"] == "domain"
    assert mods["legacy_shop.billing"]["fan_in"] == 3
    assert mods["legacy_shop.orders"]["role"] == "model"
    assert sorted(mods["legacy_shop.billing"]["dependents"]) == [
        "legacy_shop.inventory", "legacy_shop.orders", "tests.test_billing"
    ]
    assert arch["top_hubs"][0]["qualified_name"] == "legacy_shop.billing"


def test_architecture_graph_artifact_endpoint(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    doc = client.get(f"/runs/{run['id']}/architecture/graph").json()
    assert doc["schema"] == "archon.graph.v1"
    assert "components" in doc and "modules" in doc
    node_qns = {n.get("qualified_name") for n in doc["modules"]["nodes"]}
    assert "legacy_shop.calculator" in node_qns


def test_modules_endpoint_filters(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    sid = run["snapshot_id"]
    all_mods = client.get(f"/snapshots/{sid}/modules").json()
    assert len(all_mods) == 8
    domain = client.get(f"/snapshots/{sid}/modules?role=domain").json()
    assert {m["qualified_name"] for m in domain} == {
        "legacy_shop.calculator", "legacy_shop.billing", "legacy_shop.inventory"
    }
    in_cycle = client.get(f"/snapshots/{sid}/modules?in_cycle=true").json()
    assert in_cycle == []


def test_dependencies_endpoint_returns_derived_edges(client, test_repo, run_worker_once):
    run = _completed(client, test_repo, run_worker_once)
    sid = run["snapshot_id"]
    depends = client.get(f"/snapshots/{sid}/dependencies?kind=DEPENDS_ON").json()
    assert len(depends) == 5
    tested = client.get(f"/snapshots/{sid}/dependencies?kind=TESTED_BY").json()
    assert len(tested) == 2


def test_architecture_404_and_409(client, test_repo, run_worker_once):
    assert client.get("/runs/run_missing/architecture").status_code == 404
    assert client.get("/snapshots/snap_missing/modules").status_code == 404
    # a run that exists but has not been analyzed -> 409
    repo = client.post("/repositories", json={"url": str(test_repo)}).json()
    run = client.post(f"/repositories/{repo['id']}/runs", json={"mode": "INGEST_ONLY"}).json()
    run_worker_once()
    r = client.get(f"/runs/{run['id']}/architecture")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"
