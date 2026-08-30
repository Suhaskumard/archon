"""Analysis worker loop (spec section 15).

Claims one queued job at a time, runs the pipeline inside a transaction, and records the
outcome. Safe to run as multiple processes against PostgreSQL (SKIP LOCKED claiming);
one process is enough for SQLite dev/test.
"""

from __future__ import annotations

import signal
import time

from archon.config import get_settings
from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.logging import get_logger
from archon.db.base import session_scope
from archon.db.models import Job
from archon.jobs.manager import JobManager
from archon.pipeline.orchestrator import PipelineOrchestrator

log = get_logger("archon.worker")


class Worker:
    def __init__(self) -> None:
        self.jobs = JobManager()
        self.orchestrator = PipelineOrchestrator(jobs=self.jobs)
        self._stop = False

    def request_stop(self, *_a) -> None:
        self._stop = True
        log.info("worker stop requested")

    def run_forever(self, *, max_iterations: int | None = None) -> None:
        settings = get_settings()
        signal.signal(signal.SIGINT, self.request_stop)
        try:
            signal.signal(signal.SIGTERM, self.request_stop)
        except (ValueError, AttributeError):  # pragma: no cover - non-main thread / windows
            pass
        log.info("worker started")
        iterations = 0
        while not self._stop:
            worked = self.tick()
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            if not worked:
                time.sleep(settings.worker_poll_interval_seconds)
        log.info("worker stopped")

    def tick(self) -> bool:
        """Process at most one job. Returns True if a job was handled."""
        with session_scope() as session:
            self.jobs.requeue_stale(session)
            job = self.jobs.claim_next(session)
            if job is None:
                return False
            job_id = job.id
            run_id = job.run_id

        try:
            with session_scope() as session:
                job = session.get(Job, job_id)
                result = self.orchestrator.run(session, run_id, job=job)
                self.jobs.finish(session, job, succeeded=True)
            log.info(
                "job succeeded",
                extra={"extra_fields": {"job_id": job_id, "snapshot_id": result.snapshot_id}},
            )
        except ArchonError as exc:
            retryable = exc.recoverability == Recoverability.TRANSIENT
            with session_scope() as session:
                job = session.get(Job, job_id)
                if exc.code == ErrorCode.JOB_CANCELLED:
                    self.jobs.finish(session, job, succeeded=False, cancelled=True)
                else:
                    payload = {**exc.to_dict()["error"], "retryable": retryable}
                    self.jobs.finish(session, job, succeeded=False, error=payload)
            log.warning(
                "job failed",
                extra={
                    "extra_fields": {
                        "job_id": job_id,
                        "code": exc.code.value,
                        "message": exc.message,
                    }
                },
            )
        except Exception as exc:  # unexpected - fail hard, never swallow (spec section 54)
            with session_scope() as session:
                job = session.get(Job, job_id)
                self.jobs.finish(
                    session,
                    job,
                    succeeded=False,
                    error={
                        "code": ErrorCode.INTERNAL.value,
                        "message": f"unexpected error: {exc}",
                        "recoverability": Recoverability.NON_RECOVERABLE.value,
                        "retryable": False,
                    },
                )
            log.exception("job crashed", extra={"extra_fields": {"job_id": job_id}})
        return True


def main() -> None:  # pragma: no cover - process entrypoint
    Worker().run_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
