"""DB-backed job queue (spec section 15).

Postgres uses ``SELECT ... FOR UPDATE SKIP LOCKED`` for safe multi-worker claiming;
SQLite (single-worker dev/test) falls back to a plain transactional read. Concurrency is
bounded by ``max_concurrent_runs`` and de-duplicated by ``dedupe_key`` (one running run
per repository + config).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archon.config import get_settings
from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.ids import new_id
from archon.core.logging import get_logger
from archon.core.observability import audit
from archon.core.versions import current_versions
from archon.db.models import AnalysisRun, Job
from archon.domain.enums import JobState, JobType, RunMode, RunState
from archon.jobs.state_machine import RunStateMachine

log = get_logger("archon.jobs")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JobManager:
    def create_run_with_job(
        self,
        session: Session,
        *,
        repository_id: str,
        mode: RunMode = RunMode.INGEST_ONLY,
        requested_ref: str | None = None,
        config_hash: str | None = None,
        idempotency_key: str | None = None,
        priority: int = 100,
        trigger: dict | None = None,
        changed_paths: list[str] | None = None,
    ) -> Job:
        """Create an ``AnalysisRun`` (PENDING->QUEUED) plus its ``Job`` (QUEUED).

        If ``idempotency_key`` matches an existing job, that job is returned unchanged.
        """
        if idempotency_key:
            existing = session.scalar(
                select(Job).where(Job.idempotency_key == idempotency_key)
            )
            if existing:
                log.info("idempotent job hit", extra={"extra_fields": {"job_id": existing.id}})
                return existing

        dedupe_key = f"{repository_id}:{config_hash or ''}"
        active_dupe = session.scalar(
            select(Job.id)
            .join(AnalysisRun, Job.run_id == AnalysisRun.id)
            .where(
                Job.dedupe_key == dedupe_key,
                Job.state.in_([JobState.QUEUED, JobState.RUNNING]),
            )
        )
        if active_dupe:
            raise ArchonError(
                ErrorCode.CONFLICT,
                "an analysis for this repository and configuration is already in progress",
                context={"dedupe_key": dedupe_key, "job_id": active_dupe},
                recoverability=Recoverability.RECOVERABLE,
                suggested_action="Wait for the running analysis to finish or cancel it first.",
            )

        run = AnalysisRun(
            id=new_id("run"),
            repository_id=repository_id,
            mode=mode,
            requested_ref=requested_ref,
            state=RunState.PENDING,
            engine_versions=current_versions(),
            config_hash=config_hash,
            trigger=trigger,
            changed_paths=changed_paths,
        )
        session.add(run)
        RunStateMachine(run.state).transition(RunState.QUEUED)
        run.state = RunState.QUEUED

        job = Job(
            id=new_id("job"),
            run_id=run.id,
            type=JobType.ANALYSIS,
            state=JobState.QUEUED,
            priority=priority,
            idempotency_key=idempotency_key,
            dedupe_key=dedupe_key,
        )
        session.add(job)
        session.flush()
        audit("run.queued", run_id=run.id, job_id=job.id, mode=mode.value,
              trigger=(trigger or {}).get("source", "api"))
        log.info(
            "run+job created",
            extra={"extra_fields": {"run_id": run.id, "job_id": job.id, "mode": mode.value}},
        )
        return job

    # --- worker side --------------------------------------------------------------

    def _running_count(self, session: Session) -> int:
        return int(
            session.scalar(select(func.count(Job.id)).where(Job.state == JobState.RUNNING)) or 0
        )

    def claim_next(self, session: Session) -> Job | None:
        settings = get_settings()
        if self._running_count(session) >= settings.max_concurrent_runs:
            return None

        stmt = (
            select(Job)
            .where(Job.state == JobState.QUEUED)
            .order_by(Job.priority.asc(), Job.created_at.asc())
            .limit(1)
        )
        if session.bind and session.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        job = session.scalar(stmt)
        if job is None:
            return None

        job.state = JobState.RUNNING
        job.attempts += 1
        job.started_at = _utcnow()
        job.heartbeat_at = _utcnow()
        run = session.get(AnalysisRun, job.run_id)
        assert run is not None
        sm = RunStateMachine(run.state)
        sm.transition(RunState.RUNNING)
        run.state = RunState.RUNNING
        run.started_at = run.started_at or _utcnow()
        session.flush()
        log.info("job claimed", extra={"extra_fields": {"job_id": job.id, "attempt": job.attempts}})
        return job

    def heartbeat(self, session: Session, job: Job, *, progress_pct: float | None = None) -> None:
        job.heartbeat_at = _utcnow()
        if progress_pct is not None:
            job.progress_pct = progress_pct
            run = session.get(AnalysisRun, job.run_id)
            if run:
                run.progress_pct = progress_pct
        session.flush()

    def is_cancel_requested(self, session: Session, job: Job) -> bool:
        session.refresh(job, attribute_names=["cancel_requested"])
        return job.cancel_requested

    def request_cancel(self, session: Session, run_id: str) -> None:
        job = session.scalar(select(Job).where(Job.run_id == run_id))
        if job is None:
            raise ArchonError(
                ErrorCode.NOT_FOUND,
                f"no job for run {run_id!r}",
                context={"run_id": run_id},
            )
        if job.state in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED):
            raise ArchonError(
                ErrorCode.CONFLICT,
                "job already finished",
                context={"job_id": job.id, "state": job.state.value},
                suggested_action="Nothing to cancel.",
            )
        job.cancel_requested = True
        session.flush()

    def finish(
        self,
        session: Session,
        job: Job,
        *,
        succeeded: bool,
        cancelled: bool = False,
        error: dict | None = None,
    ) -> None:
        job.finished_at = _utcnow()
        run = session.get(AnalysisRun, job.run_id)
        assert run is not None
        if cancelled:
            job.state = JobState.CANCELLED
            run.state = RunState.CANCELLED
        elif succeeded:
            job.state = JobState.SUCCEEDED
            run.state = RunState.COMPLETED
        else:
            job.error = error
            run.error = error
            if job.attempts < job.max_attempts and (error or {}).get("retryable"):
                job.state = JobState.QUEUED
                job.started_at = None
                run.state = RunState.QUEUED
            else:
                job.state = JobState.FAILED
                run.state = RunState.FAILED
        run.ended_at = _utcnow() if run.state != RunState.QUEUED else None
        session.flush()
        log.info(
            "job finished",
            extra={"extra_fields": {"job_id": job.id, "state": job.state.value}},
        )

    def requeue_stale(self, session: Session) -> int:
        settings = get_settings()
        cutoff = _utcnow() - timedelta(seconds=settings.job_heartbeat_timeout_seconds)
        stale = session.scalars(
            select(Job).where(Job.state == JobState.RUNNING, Job.heartbeat_at < cutoff)
        ).all()
        for job in stale:
            run = session.get(AnalysisRun, job.run_id)
            if job.attempts >= job.max_attempts:
                job.state = JobState.FAILED
                job.error = {"code": ErrorCode.TIMEOUT.value, "message": "worker heartbeat lost"}
                if run:
                    run.state = RunState.FAILED
                    run.error = job.error
                audit("run.failed", run_id=job.run_id, job_id=job.id, code="TIMEOUT",
                      message="worker heartbeat lost")
            else:
                job.state = JobState.QUEUED
                job.started_at = None
                if run:
                    run.state = RunState.QUEUED
                audit("run.requeued", run_id=job.run_id, job_id=job.id, attempt=job.attempts)
        if stale:
            session.flush()
            log.info("requeued stale jobs", extra={"extra_fields": {"count": len(stale)}})
        return len(stale)
