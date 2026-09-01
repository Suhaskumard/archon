"""Phase 10 acceptance contract (spec sections 4, 44, 53, 60).

Two runs of the same repository hit the same planted bug. The first run's VERIFIED
patch is recorded as an Incident; the second run's investigation cites that incident
as historical context - without it changing the second investigation's own
confidence, which is derived from fresh evidence exactly as before (Principle 15).
Requires the real Docker sandbox (``sandbox_image_available``).
"""

from __future__ import annotations

from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import AnalysisRun, Incident, Investigation, Job, Repository
from archon.domain.enums import JobState, RunMode, RunState
from archon.jobs.manager import JobManager
from archon.jobs.worker import Worker
from archon.providers.repo import provider_for
from tests.conftest import terminal_stage


def _run(repo_id: str) -> str:
    jobs = JobManager()
    with session_scope() as s:
        rid = jobs.create_run_with_job(s, repository_id=repo_id, mode=RunMode.FULL).run_id
    w = Worker()
    while w.tick():
        pass
    return rid


def test_second_investigation_cites_first_incident(test_repo, sandbox_image_available):
    with session_scope() as s:
        provider = provider_for(str(test_repo))
        ref = provider.parse(str(test_repo))
        repo = Repository(provider=provider.kind, url=ref.canonical_url, name=ref.name)
        s.add(repo)
        s.flush()
        repo_id = repo.id

    rid1 = _run(repo_id)
    with session_scope() as s:
        run1 = s.get(AnalysisRun, rid1)
        assert s.get(Job, run1.job.id).state is JobState.SUCCEEDED
        assert run1.state is RunState.COMPLETED
        assert run1.last_completed_stage is terminal_stage("FULL")

        incidents1 = s.scalars(select(Incident).where(Incident.run_id == rid1)).all()
        assert len(incidents1) == 1
        incident1 = incidents1[0]
        investigation1 = s.scalar(select(Investigation).where(Investigation.run_id == rid1))
        run1_confidence = investigation1.confidence

    rid2 = _run(repo_id)
    with session_scope() as s:
        run2 = s.get(AnalysisRun, rid2)
        assert run2.state is RunState.COMPLETED

        investigation2 = s.scalar(select(Investigation).where(Investigation.run_id == rid2))
        assert investigation2 is not None
        assert incident1.id in investigation2.cited_incident_ids
        # cited, not substituted: the fresh investigation's own confidence is
        # unchanged by the historical citation.
        assert investigation2.confidence == run1_confidence

        # the second run also verifies its own repair and records its own incident.
        incidents2 = s.scalars(select(Incident).where(Incident.run_id == rid2)).all()
        assert len(incidents2) == 1
        assert incidents2[0].id != incident1.id
