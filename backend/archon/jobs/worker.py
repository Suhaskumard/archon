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
from archon.core.observability import audit, metrics, record_run_outcome
from archon.db.base import session_scope
from archon.db.models import AnalysisRun, Job
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
        audit("worker.draining")
        log.info("worker stop requested - will finish the in-flight job, then exit")

    def run_forever(self, *, max_iterations: int | None = None) -> None:
        settings = get_settings()
        signal.signal(signal.SIGINT, self.request_stop)
        try:
            signal.signal(signal.SIGTERM, self.request_stop)
        except (ValueError, AttributeError):  # pragma: no cover - non-main thread / windows
            pass
        self._reap_orphans()
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

    @staticmethod
    def _reap_orphans() -> None:
        """Best-effort cleanup of anything a crashed prior worker left behind."""
        from archon.sandbox.reaper import reap_orphan_containers
        from archon.workspace.manager import WorkspaceManager

        try:
            WorkspaceManager().reap_orphans()
        except Exception:  # pragma: no cover - startup hygiene only, never fatal
            log.exception("workspace reap failed")
        try:
            reap_orphan_containers()
        except Exception:  # pragma: no cover - docker may be unavailable; never fatal
            log.exception("sandbox container reap failed")

    def tick(self) -> bool:
        """Process at most one job. Returns True if a job was handled."""
        with session_scope() as session:
            self.jobs.requeue_stale(session)
            job = self.jobs.claim_next(session)
            if job is None:
                return False
            job_id = job.id
            run_id = job.run_id
            mode = session.get(AnalysisRun, run_id).mode.value
        audit("run.claimed", run_id=run_id, job_id=job_id, mode=mode)
        metrics.runs_active.inc()

        try:
            with session_scope() as session:
                job = session.get(Job, job_id)
                result = self.orchestrator.run(session, run_id, job=job)
                self.jobs.finish(session, job, succeeded=True)
            record_run_outcome("completed", mode)
            audit("run.completed", run_id=run_id, job_id=job_id, mode=mode)
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
                    outcome = "cancelled"
                else:
                    payload = {**exc.to_dict()["error"], "retryable": retryable}
                    self.jobs.finish(session, job, succeeded=False, error=payload)
                    outcome = "requeued" if retryable and job.state.value == "QUEUED" else "failed"
            record_run_outcome(outcome, mode)
            audit(f"run.{outcome}", run_id=run_id, job_id=job_id, mode=mode,
                  code=exc.code.value, message=exc.message)
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
            record_run_outcome("failed", mode)
            audit("run.failed", run_id=run_id, job_id=job_id, mode=mode, code="INTERNAL")
            log.exception("job crashed", extra={"extra_fields": {"job_id": job_id}})
        finally:
            metrics.runs_active.dec()
        return True


def main() -> None:  # pragma: no cover - process entrypoint
    Worker().run_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
