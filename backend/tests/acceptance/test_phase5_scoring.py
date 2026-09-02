"""Phase 5 acceptance contract (spec sections 4, 27-30, 53, 60).

FULL run on the scoring fixture: a churny/complex/untested module ranks riskier than a
stable equivalent; a richer-evidence repo scores a higher (and more confident)
understanding than a sparse one; the coverage proxy documentedly does not silently
suppress risk for a module that merely has *a* test file.
"""

from __future__ import annotations

from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import (
    AnalysisRun,
    Component,
    Hotspot,
    Job,
    LegacyDNA,
    Repository,
)
from archon.domain.enums import ComponentKind, JobState, RunMode, RunState
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from tests.conftest import terminal_stage


def _run(repo_path) -> str:
    jobs = JobManager()
    with session_scope() as s:
        provider = provider_for(str(repo_path))
        ref = provider.parse(str(repo_path))
        repo = Repository(provider=provider.kind, url=ref.canonical_url, name=ref.name)
        s.add(repo)
        s.flush()
        rid = jobs.create_run_with_job(s, repository_id=repo.id, mode=RunMode.ANALYSIS_ONLY).run_id
    w = Worker()
    while w.tick():
        pass
    return rid


def _module_dna(s, run_id, snapshot_id, qn):
    comp = s.scalar(
        select(Component).where(
            Component.snapshot_id == snapshot_id,
            Component.qualified_name == qn,
            Component.kind == ComponentKind.MODULE,
        )
    )
    dna = s.scalar(select(LegacyDNA).where(LegacyDNA.run_id == run_id, LegacyDNA.component_id == comp.id))
    hotspot = s.scalar(select(Hotspot).where(Hotspot.run_id == run_id, Hotspot.component_id == comp.id))
    return comp, dna, hotspot


def test_run_completes_at_scoring_hotspots(scoring_repo):
    rid = _run(scoring_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert s.get(Job, run.job.id).state is JobState.SUCCEEDED
        assert run.state is RunState.COMPLETED
        assert run.last_completed_stage is terminal_stage("ANALYSIS_ONLY")
        for key in ("legacy_risk", "hotspot", "understanding", "tech_debt"):
            assert key in run.engine_versions


def test_risky_component_ranks_above_stable(scoring_repo):
    rid = _run(scoring_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        sid = run.snapshot_id
        _, risky_dna, risky_hot = _module_dna(s, rid, sid, "scoring_shop.pricing_engine")
        _, stable_dna, stable_hot = _module_dna(s, rid, sid, "scoring_shop.tax_rules")

        assert risky_dna.legacy_risk_score > stable_dna.legacy_risk_score
        assert risky_dna.category in ("HIGH", "CRITICAL")
        assert stable_dna.category in ("LOW", "MODERATE")

        assert risky_hot.score > stable_hot.score
        assert risky_hot.classification in ("RISKY", "CRITICAL")
        assert stable_hot.classification == "STABLE"


def test_documented_coverage_exception_bounded_and_intended(scoring_repo):
    """``shipping_calculator`` has real churn/complexity *and* a TESTED_BY edge (the
    coverage proxy = 0.5). Its risk must sit strictly between the stable and risky
    fixtures - proving the coverage proxy's small weight tempers but does not erase
    the churn/complexity signal, and that this is the intended, documented behaviour
    (not an accident of a badly-tuned weight)."""
    rid = _run(scoring_repo)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        sid = run.snapshot_id
        _, risky_dna, _ = _module_dna(s, rid, sid, "scoring_shop.pricing_engine")
        _, stable_dna, _ = _module_dna(s, rid, sid, "scoring_shop.tax_rules")
        _, exception_dna, _ = _module_dna(s, rid, sid, "scoring_shop.shipping_calculator")

        assert stable_dna.legacy_risk_score < exception_dna.legacy_risk_score < risky_dna.legacy_risk_score
        assert exception_dna.coverage_is_proxy is True
        assert exception_dna.coverage == 0.5
        # the coverage-gap contribution is documented in the breakdown, never hidden
        breakdown = exception_dna.factor_breakdown
        assert breakdown["coverage_is_proxy"] is True
        assert "coverage_gap" in breakdown["normalized"]


def test_stronger_evidence_increases_understanding_score_and_confidence(tmp_path, scoring_repo):
    rid_rich = _run(scoring_repo)

    # a minimal, sparse-evidence repo: one file, one commit, no tests, no history depth
    sparse_repo = tmp_path / "sparse_repo"
    sparse_repo.mkdir()
    from tests.fixtures.build_test_repo import _git, _write

    _write(sparse_repo, {
        "solo.py": "def f(x):\n    return x\n",
    })
    _git(["init", "-b", "main"], sparse_repo)
    _git(["config", "user.email", "fixture@archon.test"], sparse_repo)
    _git(["config", "user.name", "ARCHON Fixture"], sparse_repo)
    _git(["config", "commit.gpgsign", "false"], sparse_repo)
    _git(["add", "-A"], sparse_repo)
    _git(["commit", "-m", "solo"], sparse_repo, when="2026-08-30T12:00:00")

    rid_sparse = _run(sparse_repo)

    with session_scope() as s:
        from archon.core.artifacts import read_json
        from archon.db.models import AnalysisArtifact

        art_rich = s.scalar(
            select(AnalysisArtifact).where(
                AnalysisArtifact.run_id == rid_rich, AnalysisArtifact.kind == "understanding"
            )
        )
        art_sparse = s.scalar(
            select(AnalysisArtifact).where(
                AnalysisArtifact.run_id == rid_sparse, AnalysisArtifact.kind == "understanding"
            )
        )
        rich = read_json(art_rich)
        sparse = read_json(art_sparse)

        assert rich["score"] > sparse["score"]
        assert rich["confidence"] > sparse["confidence"]
