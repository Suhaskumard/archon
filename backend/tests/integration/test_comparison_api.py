"""Phase 11 - repository comparison API (spec sections 45, 47).

Builds two analysis-complete runs of one repository directly (no sandbox needed -
comparison only reads analysis-stage rows) and exercises the three endpoints plus
the guard paths.
"""

from __future__ import annotations

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisArtifact,
    AnalysisRun,
    ChangeAssessment,
    Component,
    LegacyDNA,
    Repository,
    RepositorySnapshot,
)
from archon.domain.enums import (
    ComponentKind,
    ProviderKind,
    RunMode,
    RunState,
    Stage,
)


def _run(session, repo_id: str, sha: str, modules: dict[str, tuple[float, str, float, str]]) -> str:
    snap = RepositorySnapshot(repository_id=repo_id, commit_sha=sha)
    session.add(snap)
    session.flush()
    run = AnalysisRun(
        repository_id=repo_id, snapshot_id=snap.id, mode=RunMode.ANALYSIS_ONLY,
        state=RunState.COMPLETED, last_completed_stage=Stage.ANALYZING_CHANGE_IMPACT,
    )
    session.add(run)
    session.flush()
    for qn, (risk, cat, safety, scat) in modules.items():
        c = Component(
            snapshot_id=snap.id, kind=ComponentKind.MODULE, name=qn.split(".")[-1],
            qualified_name=qn, path=qn.replace(".", "/") + ".py",
        )
        session.add(c)
        session.flush()
        session.add(LegacyDNA(
            run_id=run.id, snapshot_id=snap.id, component_id=c.id, coverage=0.7,
            legacy_risk_score=risk, category=cat, confidence=0.9, produced_by="legacy_risk.v1",
        ))
        session.add(ChangeAssessment(
            run_id=run.id, snapshot_id=snap.id, component_id=c.id,
            engine_version="change_safety.v1", safety_score=safety, risk_category=scat,
            confidence=0.9, produced_by="change_safety.v1",
        ))
    session.flush()
    return run.id


def _fixture(refresh_billing_risk: float = 80.0, url: str = "/tmp/cmp"):
    with session_scope() as s:
        repo = Repository(provider=ProviderKind.LOCAL, url=url, name="cmp")
        s.add(repo)
        s.flush()
        base = _run(s, repo.id, "a" * 40, {
            "pkg.calc": (10.0, "LOW", 90.0, "SAFE"),
            "pkg.billing": (40.0, "MODERATE", 70.0, "CAUTION"),
        })
        head = _run(s, repo.id, "b" * 40, {
            "pkg.calc": (10.0, "LOW", 90.0, "SAFE"),
            "pkg.billing": (refresh_billing_risk, "HIGH", 45.0, "RISKY"),
            "pkg.inventory": (25.0, "MODERATE", 65.0, "CAUTION"),
        })
        return repo.id, base, head


def test_create_and_fetch_comparison(client):
    repo_id, base, head = _fixture()
    resp = client.post(
        f"/repositories/{repo_id}/comparisons",
        json={"base_run_id": base, "head_run_id": head},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["base_run_id"] == base and body["head_run_id"] == head
    assert body["base_commit_sha"] == "a" * 40
    assert body["report"]["architecture"]["modules_added"] == ["pkg.inventory"]
    assert "pkg.billing" in body["report"]["legacy_dna"]["risk_category_regressions"]
    assert body["summary"]["modules_added"] == 1

    got = client.get(f"/comparisons/{body['id']}").json()
    assert got["id"] == body["id"]
    assert got["report"]["change_safety"]["change_safety_regressions"] == ["pkg.billing"]


def test_comparison_is_idempotent_and_listed(client):
    repo_id, base, head = _fixture()
    first = client.post(
        f"/repositories/{repo_id}/comparisons",
        json={"base_run_id": base, "head_run_id": head},
    ).json()
    second = client.post(
        f"/repositories/{repo_id}/comparisons",
        json={"base_run_id": base, "head_run_id": head},
    ).json()
    assert first["id"] == second["id"]

    rows = client.get(f"/repositories/{repo_id}/comparisons").json()
    assert [r["id"] for r in rows] == [first["id"]]
    assert "report" not in rows[0]  # summary list omits the heavy payload


def test_comparison_writes_an_artifact(client):
    repo_id, base, head = _fixture()
    body = client.post(
        f"/repositories/{repo_id}/comparisons",
        json={"base_run_id": base, "head_run_id": head},
    ).json()
    assert body["report_artifact_id"]
    with session_scope() as s:
        art = s.get(AnalysisArtifact, body["report_artifact_id"])
        assert art is not None
        assert art.run_id == head
        assert art.kind == f"repo_comparison_{body['id']}"


def test_guard_paths(client):
    repo_id, base, head = _fixture()

    same = client.post(
        f"/repositories/{repo_id}/comparisons",
        json={"base_run_id": base, "head_run_id": base},
    )
    assert same.status_code == 409

    unknown = client.post(
        f"/repositories/{repo_id}/comparisons",
        json={"base_run_id": base, "head_run_id": "run_missing"},
    )
    assert unknown.status_code == 404

    assert client.post(
        "/repositories/repo_missing/comparisons",
        json={"base_run_id": base, "head_run_id": head},
    ).status_code == 404
    assert client.get("/comparisons/cmp_missing").status_code == 404


def test_cross_repository_runs_rejected(client):
    repo_id, base, _head = _fixture()
    other_repo_id, _b, other_head = _fixture(url="/tmp/cmp-other")
    resp = client.post(
        f"/repositories/{repo_id}/comparisons",
        json={"base_run_id": base, "head_run_id": other_head},
    )
    assert resp.status_code == 409
    assert other_repo_id != repo_id


def test_incomplete_run_rejected(client):
    repo_id, base, head = _fixture()
    with session_scope() as s:
        r = s.get(AnalysisRun, head)
        r.last_completed_stage = Stage.ANALYZING_SOURCE  # before ASSESSING_CHANGE_SAFETY
    resp = client.post(
        f"/repositories/{repo_id}/comparisons",
        json={"base_run_id": base, "head_run_id": head},
    )
    assert resp.status_code == 409
