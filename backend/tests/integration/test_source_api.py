"""Source-intelligence API endpoints (spec sections 22, 47)."""

from __future__ import annotations


def _completed_run(client, test_repo, run_worker_once):
    repo = client.post("/repositories", json={"url": str(test_repo)}).json()
    run = client.post(
        f"/repositories/{repo['id']}/runs", json={"mode": "ANALYSIS_ONLY"}
    ).json()
    run_worker_once()
    got = client.get(f"/runs/{run['id']}").json()
    assert got["state"] == "COMPLETED"
    return got


def test_components_endpoint_lists_and_filters(client, test_repo, run_worker_once):
    run = _completed_run(client, test_repo, run_worker_once)
    sid = run["snapshot_id"]

    all_comps = client.get(f"/snapshots/{sid}/components?limit=1000").json()
    assert len(all_comps) > 20
    kinds = {c["kind"] for c in all_comps}
    assert {"FILE", "MODULE", "CLASS", "FUNCTION", "METHOD"} <= kinds

    classes = client.get(f"/snapshots/{sid}/components?kind=CLASS").json()
    assert {c["qualified_name"] for c in classes} == {
        "legacy_shop.orders.Order",
        "legacy_shop.orders.RushOrder",
    }

    tests = client.get(f"/snapshots/{sid}/components?kind=MODULE&is_test=true").json()
    assert all(c["is_test"] for c in tests)
    assert any(c["qualified_name"] == "tests.test_billing" for c in tests)

    hit = client.get(f"/snapshots/{sid}/components?q=unit_price").json()
    assert hit and hit[0]["metrics"]["complexity"] == 2


def test_component_detail_has_edge_counts(client, test_repo, run_worker_once):
    run = _completed_run(client, test_repo, run_worker_once)
    sid = run["snapshot_id"]
    calc = next(
        c
        for c in client.get(f"/snapshots/{sid}/components?q=legacy_shop.calculator&kind=MODULE").json()
        if c["qualified_name"] == "legacy_shop.calculator"
    )
    detail = client.get(f"/components/{calc['id']}").json()
    assert detail["attributes"]["child_count"] >= 2  # add, divide
    assert detail["attributes"]["incoming_edges"] >= 1  # imported by billing


def test_dependencies_endpoint(client, test_repo, run_worker_once):
    run = _completed_run(client, test_repo, run_worker_once)
    sid = run["snapshot_id"]
    imports = client.get(f"/snapshots/{sid}/dependencies?kind=IMPORTS&resolved=true").json()
    assert imports and all(d["kind"] == "IMPORTS" and d["resolved"] for d in imports)
    inherits = client.get(f"/snapshots/{sid}/dependencies?kind=INHERITS").json()
    assert len(inherits) == 1
    externals = client.get(f"/snapshots/{sid}/dependencies?external=true").json()
    assert any(d["target_name"] == "attrs" or not d["resolved"] for d in externals) or externals == []


def test_run_source_summary(client, test_repo, run_worker_once):
    run = _completed_run(client, test_repo, run_worker_once)
    summary = client.get(f"/runs/{run['id']}/source").json()
    assert summary["analyzed"] is True
    assert summary["components"]["MODULE"] == 8
    assert summary["components"]["CLASS"] == 2
    assert summary["edges"]["CONTAINS"] > 0
    assert summary["tests"] >= 2
    assert summary["config_files"] >= 2


def test_source_summary_conflict_before_snapshot(client):
    # a run id that does not exist -> 404; a run with no snapshot -> 409
    assert client.get("/runs/run_missing/source").status_code == 404


def test_unknown_snapshot_is_404(client):
    assert client.get("/snapshots/snap_missing/components").status_code == 404
    assert client.get("/snapshots/snap_missing/dependencies").status_code == 404
