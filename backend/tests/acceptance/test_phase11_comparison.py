"""Phase 11 acceptance contract (spec section 45).

Analyse the fixture repository at two commits and diff the two runs. The spec's bar:
"fixture at two commits -> expected deltas (added module, risk change)". Commit 1 has
only ``calculator`` + ``billing``; commit 3 adds ``inventory`` + ``orders`` and guards
``billing.unit_price`` - so the comparison must surface at least one added module and
at least one risk / change-safety movement.

Requires the real Docker sandbox (``sandbox_image_available``) - a FULL run reaches
``COMPLETED`` only with it.
"""

from __future__ import annotations

from archon.comparison import build_comparison
from archon.comparison.differ import COMPARISON_VERSION
from archon.core.artifacts import read_json
from archon.db.base import session_scope
from archon.db.models import AnalysisArtifact, AnalysisRun, Repository
from archon.domain.enums import RunMode, RunState
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from archon.providers.repo.gitcli import run_git


def _run(repo_id: str, ref: str, tag: str) -> str:
    jobs = JobManager()
    with session_scope() as s:
        rid = jobs.create_run_with_job(
            s, repository_id=repo_id, mode=RunMode.FULL, requested_ref=ref, config_hash=tag
        ).run_id
    w = Worker()
    while w.tick():
        pass
    return rid


def test_two_commit_comparison_surfaces_added_module_and_risk_change(
    test_repo, sandbox_image_available
):
    first = run_git(["rev-list", "--max-parents=0", "HEAD"], cwd=test_repo).stdout.strip()
    head_sha = run_git(["rev-parse", "HEAD"], cwd=test_repo).stdout.strip()

    with session_scope() as s:
        provider = provider_for(str(test_repo))
        ref = provider.parse(str(test_repo))
        repo = Repository(provider=provider.kind, url=ref.canonical_url, name=ref.name)
        s.add(repo)
        s.flush()
        repo_id = repo.id

    base_run = _run(repo_id, first, "base")
    head_run = _run(repo_id, head_sha, "head")

    with session_scope() as s:
        assert s.get(AnalysisRun, base_run).state is RunState.COMPLETED
        assert s.get(AnalysisRun, head_run).state is RunState.COMPLETED

        row = build_comparison(
            s, repo_id, s.get(AnalysisRun, base_run), s.get(AnalysisRun, head_run)
        )
        cid = row.id
        report = row.report
        artifact_id = row.report_artifact_id

        # (a) added module - inventory and orders appear only from commit 2 on
        added = report["architecture"]["modules_added"]
        assert any(qn.endswith(".inventory") for qn in added), added
        assert row.summary["modules_added"] >= 1

        # (b) risk change - billing was guarded between the two commits, so some
        # legacy-risk or change-safety signal must have moved
        moved = (
            report["legacy_dna"]["changed"]
            or report["change_safety"]["changed"]
            or report["risk"].get("changed")
        )
        assert moved, "expected at least one risk / change-safety delta between commits"

        # report persisted as an artifact (spec: "report as artifact")
        art = s.get(AnalysisArtifact, artifact_id)
        assert art is not None and art.run_id == head_run
        assert read_json(art)["produced_by"] == COMPARISON_VERSION

    # recompute returns the same row (idempotent)
    with session_scope() as s:
        again = build_comparison(
            s, repo_id, s.get(AnalysisRun, base_run), s.get(AnalysisRun, head_run)
        )
        assert again.id == cid
