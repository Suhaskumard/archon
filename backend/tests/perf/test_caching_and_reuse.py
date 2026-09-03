"""Cache-key correctness: snapshot-scoped extraction/graph reuse across runs (spec section 53).

Run with:  pytest -m perf
"""

from __future__ import annotations

import subprocess

import pytest

from archon.db.base import session_scope
from archon.db.models import AnalysisRun, Component, Dependency, Repository
from archon.domain.enums import RunMode, RunState
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from tests.conftest import terminal_stage

pytestmark = pytest.mark.perf


def _register(session, path) -> Repository:
    prov = provider_for(str(path))
    ref = prov.parse(str(path))
    repo = Repository(provider=prov.kind, url=ref.canonical_url, name=ref.name)
    session.add(repo)
    session.flush()
    return repo


def _run(jobs, repo_id, *, cfg) -> str:
    with session_scope() as s:
        return jobs.create_run_with_job(
            s, repository_id=repo_id, mode=RunMode.ANALYSIS_ONLY, config_hash=cfg
        ).run_id


def _drain(n=40):
    w = Worker()
    for _ in range(n):
        if not w.tick():
            break


def test_second_run_over_the_same_commit_reuses_the_snapshot_and_extraction(test_repo):
    jobs = JobManager()
    with session_scope() as s:
        repo = _register(s, test_repo)
        repo_id = repo.id

    r1 = _run(jobs, repo_id, cfg="reuse-1")
    _drain()
    r2 = _run(jobs, repo_id, cfg="reuse-2")
    _drain()

    with session_scope() as s:
        run1, run2 = s.get(AnalysisRun, r1), s.get(AnalysisRun, r2)
        assert run1.state is run2.state is RunState.COMPLETED
        # same commit -> ONE immutable snapshot shared by both runs
        assert run1.snapshot_id == run2.snapshot_id
        sid = run1.snapshot_id
        # components/dependencies are keyed to the snapshot, not the run -> not duplicated
        assert s.query(Component).filter_by(snapshot_id=sid).count() > 0
        n_comp = s.query(Component).filter_by(snapshot_id=sid).count()
        n_dep = s.query(Dependency).filter_by(snapshot_id=sid).count()

    # a third run must still see exactly the same row counts (idempotent reuse)
    r3 = _run(jobs, repo_id, cfg="reuse-3")
    _drain()
    with session_scope() as s:
        sid = s.get(AnalysisRun, r3).snapshot_id
        assert s.query(Component).filter_by(snapshot_id=sid).count() == n_comp
        assert s.query(Dependency).filter_by(snapshot_id=sid).count() == n_dep
        assert s.get(AnalysisRun, r3).last_completed_stage is terminal_stage("ANALYSIS_ONLY")


def test_a_new_commit_gets_a_fresh_snapshot_and_is_not_reused(test_repo):
    jobs = JobManager()
    with session_scope() as s:
        repo = _register(s, test_repo)
        repo_id = repo.id
    r1 = _run(jobs, repo_id, cfg="fresh-1")
    _drain()

    subprocess.run(["git", "commit", "--allow-empty", "-m", "new head"],
                   cwd=str(test_repo), check=True, capture_output=True)

    r2 = _run(jobs, repo_id, cfg="fresh-2")
    _drain()

    with session_scope() as s:
        run1, run2 = s.get(AnalysisRun, r1), s.get(AnalysisRun, r2)
        assert run1.snapshot_id != run2.snapshot_id  # different commit -> different snapshot
        assert run2.state is RunState.COMPLETED
