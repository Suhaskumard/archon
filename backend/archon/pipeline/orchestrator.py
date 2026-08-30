"""Pipeline orchestrator.

Walks the executable prefix of the analysis state machine for a run, one stage at a time,
persisting ``last_completed_stage`` so resumption is well-defined. Which stages run is
decided by ``run.mode`` (``_STAGE_PLANS``); every stage is idempotent (re-running a stage
first clears the rows it owns).

Implemented stages:
    INGESTING            validate + fetch metadata + secure clone into a fresh workspace
    SNAPSHOTTING         classify support, persist an immutable RepositorySnapshot
    ANALYZING_SOURCE     Python AST extraction -> components + dependencies (Phase 2)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archon.analysis.source.persist import analyze_source
from archon.config import get_settings
from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.logging import get_logger
from archon.db.models import AnalysisRun, Evidence, Repository, RepositorySnapshot
from archon.domain.enums import Classification, RunMode, RunState, Stage
from archon.jobs.manager import JobManager
from archon.jobs.state_machine import RunStateMachine
from archon.pipeline.support import assess_support
from archon.providers.repo import provider_for
from archon.workspace.manager import Workspace, WorkspaceManager

log = get_logger("archon.pipeline")

_STAGE_PLANS: dict[RunMode, tuple[Stage, ...]] = {
    RunMode.INGEST_ONLY: (Stage.INGESTING, Stage.SNAPSHOTTING),
    RunMode.ANALYSIS_ONLY: (Stage.INGESTING, Stage.SNAPSHOTTING, Stage.ANALYZING_SOURCE),
    RunMode.FULL: (Stage.INGESTING, Stage.SNAPSHOTTING, Stage.ANALYZING_SOURCE),
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class PipelineResult:
    run_id: str
    snapshot_id: str
    commit_sha: str
    support_level: str
    stages_completed: list[str]
    source: dict | None = None


class PipelineOrchestrator:
    def __init__(
        self,
        jobs: JobManager | None = None,
        workspaces: WorkspaceManager | None = None,
    ) -> None:
        self.jobs = jobs or JobManager()
        self.workspaces = workspaces or WorkspaceManager()

    def run(self, session: Session, run_id: str, *, job=None) -> PipelineResult:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            raise ArchonError(ErrorCode.NOT_FOUND, f"run {run_id!r} not found")
        if run.state != RunState.RUNNING:
            raise ArchonError(
                ErrorCode.ILLEGAL_STATE_TRANSITION,
                f"run {run_id!r} is {run.state.value}, expected RUNNING",
            )
        repository = session.get(Repository, run.repository_id)
        assert repository is not None

        plan = _STAGE_PLANS.get(run.mode, _STAGE_PLANS[RunMode.INGEST_ONLY])
        sm = RunStateMachine(run.state, run.current_stage)
        completed: list[str] = []
        clone_result = None
        snapshot: RepositorySnapshot | None = None
        source_summary: dict | None = None

        for stage in plan:
            self._check_cancel(session, job)
            sm.enter_stage(stage)
            run.current_stage = stage
            session.flush()
            self._clear_stage(session, run_id, stage)

            if stage is Stage.INGESTING:
                clone_result = self._ingest(session, run, repository)
            elif stage is Stage.SNAPSHOTTING:
                assert clone_result is not None
                snapshot = self._snapshot(session, run, repository, clone_result)
            elif stage is Stage.ANALYZING_SOURCE:
                assert clone_result is not None and snapshot is not None
                source_summary = self._source(session, run, snapshot, clone_result.workspace)

            run.last_completed_stage = stage
            run.progress_pct = 100.0 * (len(completed) + 1) / len(plan)
            completed.append(stage.value)
            session.flush()
            if job is not None:
                self.jobs.heartbeat(session, job, progress_pct=run.progress_pct)

        assert clone_result is not None and snapshot is not None
        run.ended_at = _utcnow()
        log.info(
            "pipeline finished",
            extra={"extra_fields": {"run_id": run_id, "stages": completed}},
        )
        return PipelineResult(
            run_id=run_id,
            snapshot_id=snapshot.id,
            commit_sha=snapshot.commit_sha,
            support_level=snapshot.support_level.value,
            stages_completed=completed,
            source=source_summary,
        )

    # --- stages --------------------------------------------------------------

    def _ingest(self, session: Session, run: AnalysisRun, repository: Repository):
        provider = provider_for(repository.url)
        ref = provider.parse(repository.url, ref=run.requested_ref)
        metadata = provider.fetch_metadata(ref)

        limits = get_settings().limits
        if metadata.size_bytes and metadata.size_bytes > limits.max_repo_size_bytes:
            raise ArchonError(
                ErrorCode.REPOSITORY_TOO_LARGE,
                "repository exceeds the maximum size before cloning",
                context={"size_bytes": metadata.size_bytes, "limit": limits.max_repo_size_bytes},
                recoverability=Recoverability.NON_RECOVERABLE,
                suggested_action="Raise ARCHON_LIMIT_MAX_REPO_SIZE_BYTES or pick a smaller repo.",
            )

        if not repository.default_branch:
            repository.default_branch = metadata.default_branch
        if ref.owner:
            repository.owner = repository.owner or ref.owner
        if ref.name:
            repository.name = repository.name or ref.name

        workspace = self.workspaces.create("ws")
        try:
            clone_result = provider.clone(ref, workspace)
        except Exception:
            self.workspaces.cleanup(workspace)
            raise

        self._add_evidence(
            session, run, Stage.INGESTING, Classification.FACT,
            f"Cloned {ref.slug} at {clone_result.commit_sha[:12]}",
            detail=(
                f"branch={clone_result.branch or 'detached'} "
                f"commits={clone_result.commit_count} files={clone_result.file_count} "
                f"size_bytes={clone_result.size_bytes}"
            ),
            produced_by="ingestion.v1",
            refs={"commit_sha": clone_result.commit_sha, "workspace_id": workspace.id},
        )
        if clone_result.commit_count > limits.max_git_history_commits:
            self._add_evidence(
                session, run, Stage.INGESTING, Classification.INFERENCE,
                "Git history exceeds the configured limit; archaeology will be truncated",
                detail=f"commit_count={clone_result.commit_count} limit={limits.max_git_history_commits}",
                produced_by="ingestion.v1", confidence=1.0,
            )
        return clone_result

    def _snapshot(
        self, session: Session, run: AnalysisRun, repository: Repository, clone_result
    ) -> RepositorySnapshot:
        repo_dir = clone_result.workspace.resolve_within("repo")
        assessment = assess_support(repo_dir, commit_count=clone_result.commit_count)

        snapshot = session.scalar(
            select(RepositorySnapshot).where(
                RepositorySnapshot.repository_id == repository.id,
                RepositorySnapshot.commit_sha == clone_result.commit_sha,
            )
        )
        if snapshot is None:
            snapshot = RepositorySnapshot(
                repository_id=repository.id,
                commit_sha=clone_result.commit_sha,
                branch=clone_result.branch,
                requested_ref=run.requested_ref,
                workspace_ref=str(repo_dir),
                size_bytes=clone_result.size_bytes,
                file_count=clone_result.file_count,
                commit_count=clone_result.commit_count,
                support_level=assessment.level,
                support_notes=assessment.as_notes(),
            )
            session.add(snapshot)
            session.flush()
        else:
            # immutable content; refresh the pointer to this run's live checkout
            snapshot.workspace_ref = str(repo_dir)

        run.snapshot_id = snapshot.id
        cls = (
            Classification.FACT
            if assessment.level.value == "SUPPORTED"
            else Classification.INFERENCE
        )
        self._add_evidence(
            session, run, Stage.SNAPSHOTTING, cls,
            f"Repository support level: {assessment.level.value}",
            detail="; ".join(assessment.reasons) or "meets all SUPPORTED criteria",
            produced_by="snapshot.v1", confidence=1.0,
        )
        return snapshot

    def _source(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
    ) -> dict:
        repo_dir = workspace.resolve_within("repo")
        summary = analyze_source(session, run, snapshot, repo_dir)
        log.info(
            "source stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    # --- helpers ----------------------------------------------------------

    def _check_cancel(self, session: Session, job) -> None:
        if job is not None and self.jobs.is_cancel_requested(session, job):
            raise ArchonError(
                ErrorCode.JOB_CANCELLED,
                "analysis cancelled by request",
                recoverability=Recoverability.NON_RECOVERABLE,
                suggested_action="Start a new analysis when ready.",
            )

    @staticmethod
    def _clear_stage(session: Session, run_id: str, stage: Stage) -> None:
        session.execute(
            delete(Evidence).where(Evidence.run_id == run_id, Evidence.stage == stage)
        )

    @staticmethod
    def _add_evidence(
        session: Session,
        run: AnalysisRun,
        stage: Stage,
        classification: Classification,
        summary: str,
        *,
        produced_by: str,
        detail: str | None = None,
        source_path: str | None = None,
        source_line: int | None = None,
        confidence: float | None = None,
        refs: dict | None = None,
    ) -> None:
        session.add(
            Evidence(
                run_id=run.id, stage=stage, classification=classification,
                summary=summary[:512], detail=detail, source_path=source_path,
                source_line=source_line, confidence=confidence, produced_by=produced_by, refs=refs,
            )
        )
