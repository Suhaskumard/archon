"""Pipeline orchestrator.

Walks the executable prefix of the analysis state machine for a run, one stage at a time,
persisting ``last_completed_stage`` so resumption is well-defined. Which stages run is
decided by ``run.mode`` (``_STAGE_PLANS``); every stage is idempotent (re-running a stage
first clears the rows it owns).

Implemented stages:
    INGESTING                  validate + fetch metadata + secure clone into a fresh workspace
    SNAPSHOTTING               classify support, persist an immutable RepositorySnapshot
    ANALYZING_SOURCE           Python AST extraction -> components + dependencies (Phase 2)
    ANALYZING_GIT              commits, churn/age, CHANGED_WITH / CHANGED_BY edges (Phase 4)
    BUILDING_GRAPH             derive module DEPENDS_ON / TESTED_BY edges + cycle detection (Phase 3)
    RECONSTRUCTING_ARCHITECTURE  role inference + coupling metrics + graph artifact (Phase 3)
    ARCHAEOLOGIZING            behaviour reconstruction + hidden assumptions + first AI step (Phase 4)
    SCORING_UNDERSTANDING      repository-understanding evidence-coverage score (Phase 5)
    BUILDING_LEGACY_DNA        Legacy Risk score + LegacyDNA signal breakdown (Phase 5)
    ANALYZING_TECH_DEBT        13 tech-debt detectors -> TechnicalDebtFinding rows (Phase 5)
    SCORING_HOTSPOTS           Hotspot score combining Legacy DNA + tech debt (Phase 5)
    ASSESSING_CHANGE_SAFETY    Change Safety score from coupling/centrality/callers/etc (Phase 6)
    ANALYZING_CHANGE_IMPACT    dependents/callers/tests/co-changes per module (Phase 6)
    ANALYZING_TESTS            existing-test discovery + structural test-gap candidates (Phase 7/8)
    CHARACTERIZING             bounded-input characterization baselines in the sandbox (Phase 8)
    GENERATING_TESTS           AI test generation, static+sandbox validated (Phase 8)
    EXECUTING                  run the combined suite, parse coverage, rank test gaps (Phase 7/8)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archon.analysis.archaeology.reconstruct import run_archaeology
from archon.analysis.architecture.reconstruct import reconstruct_architecture
from archon.analysis.git.persist import analyze_git
from archon.analysis.graph.derive import derive_edges
from archon.analysis.scoring.change_impact import run_change_impact
from archon.analysis.scoring.change_safety_run import run_change_safety
from archon.analysis.scoring.hotspots import run_hotspot_scoring
from archon.analysis.scoring.legacy_dna import run_legacy_risk
from archon.analysis.scoring.tech_debt import run_tech_debt_detection
from archon.analysis.scoring.understanding_run import run_understanding
from archon.analysis.source.persist import analyze_source
from archon.config import get_settings
from archon.core.artifacts import read_text
from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisArtifact,
    AnalysisRun,
    Evidence,
    Execution,
    Repository,
    RepositorySnapshot,
)
from archon.domain.enums import Classification, RunMode, RunState, Stage
from archon.execution.runner import run_existing_tests
from archon.failure.detection import detect_failures
from archon.healing.generation import generate_patches
from archon.healing.ranking import rank_patches
from archon.investigation.engine import investigate_failures
from archon.jobs.manager import JobManager
from archon.jobs.state_machine import RunStateMachine
from archon.pipeline.support import assess_support
from archon.providers.repo import provider_for
from archon.testing.characterization import run_characterization
from archon.testing.discovery import discover_existing_tests
from archon.testing.gaps import analyze_test_gaps, identify_untested_components
from archon.testing.generation import run_test_generation
from archon.verification.engine import verify_patches
from archon.workspace.manager import Workspace, WorkspaceManager

log = get_logger("archon.pipeline")

_ANALYSIS_STAGES = (
    Stage.INGESTING,
    Stage.SNAPSHOTTING,
    Stage.ANALYZING_SOURCE,
    Stage.ANALYZING_GIT,
    Stage.BUILDING_GRAPH,
    Stage.RECONSTRUCTING_ARCHITECTURE,
    Stage.ARCHAEOLOGIZING,
    Stage.SCORING_UNDERSTANDING,
    Stage.BUILDING_LEGACY_DNA,
    Stage.ANALYZING_TECH_DEBT,
    Stage.SCORING_HOTSPOTS,
    Stage.ASSESSING_CHANGE_SAFETY,
    Stage.ANALYZING_CHANGE_IMPACT,
    Stage.ANALYZING_TESTS,
    Stage.CHARACTERIZING,
    Stage.GENERATING_TESTS,
    Stage.EXECUTING,
    Stage.DETECTING_FAILURES,
    Stage.INVESTIGATING,
    Stage.GENERATING_PATCH,
    Stage.RANKING_PATCHES,
    Stage.VERIFYING_PATCH,
    Stage.REGRESSION_VERIFYING,
)
_STAGE_PLANS: dict[RunMode, tuple[Stage, ...]] = {
    RunMode.INGEST_ONLY: (Stage.INGESTING, Stage.SNAPSHOTTING),
    RunMode.ANALYSIS_ONLY: _ANALYSIS_STAGES,
    RunMode.FULL: _ANALYSIS_STAGES,
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
    architecture: dict | None = None
    git: dict | None = None
    archaeology: dict | None = None
    understanding: dict | None = None
    legacy_dna: dict | None = None
    tech_debt: dict | None = None
    hotspots: dict | None = None
    change_safety: dict | None = None
    change_impact: dict | None = None
    test_discovery: dict | None = None
    characterization: dict | None = None
    test_generation: dict | None = None
    execution: dict | None = None
    failures: dict | None = None
    investigations: dict | None = None
    patches: dict | None = None
    verification: dict | None = None


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
        architecture_summary: dict | None = None
        git_summary: dict | None = None
        archaeology_summary: dict | None = None
        understanding_summary: dict | None = None
        legacy_dna_summary: dict | None = None
        tech_debt_summary: dict | None = None
        hotspot_summary: dict | None = None
        change_safety_summary: dict | None = None
        change_impact_summary: dict | None = None
        test_discovery_summary: dict | None = None
        characterization_summary: dict | None = None
        test_generation_summary: dict | None = None
        execution_summary: dict | None = None
        failure_summary: dict | None = None
        investigation_summary: dict | None = None
        patch_summary: dict | None = None
        verification_summary: dict | None = None

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
            elif stage is Stage.ANALYZING_GIT:
                assert clone_result is not None and snapshot is not None
                git_summary = self._git(session, run, snapshot, clone_result.workspace)
            elif stage is Stage.BUILDING_GRAPH:
                assert snapshot is not None
                self._graph(session, run, snapshot)
            elif stage is Stage.RECONSTRUCTING_ARCHITECTURE:
                assert snapshot is not None
                architecture_summary = self._architecture(session, run, snapshot)
            elif stage is Stage.ARCHAEOLOGIZING:
                assert clone_result is not None and snapshot is not None
                archaeology_summary = self._archaeology(
                    session, run, snapshot, clone_result.workspace
                )
            elif stage is Stage.SCORING_UNDERSTANDING:
                assert snapshot is not None
                understanding_summary = self._understanding(session, run, snapshot)
            elif stage is Stage.BUILDING_LEGACY_DNA:
                assert snapshot is not None
                legacy_dna_summary = self._legacy_dna(session, run, snapshot)
            elif stage is Stage.ANALYZING_TECH_DEBT:
                assert clone_result is not None and snapshot is not None
                tech_debt_summary = self._tech_debt(session, run, snapshot, clone_result.workspace)
            elif stage is Stage.SCORING_HOTSPOTS:
                assert snapshot is not None
                hotspot_summary = self._hotspots(session, run, snapshot)
            elif stage is Stage.ASSESSING_CHANGE_SAFETY:
                assert snapshot is not None
                change_safety_summary = self._change_safety(session, run, snapshot)
            elif stage is Stage.ANALYZING_CHANGE_IMPACT:
                assert snapshot is not None
                change_impact_summary = self._change_impact(session, run, snapshot)
            elif stage is Stage.ANALYZING_TESTS:
                assert snapshot is not None
                test_discovery_summary = self._analyzing_tests(session, run, snapshot)
            elif stage is Stage.CHARACTERIZING:
                assert clone_result is not None and snapshot is not None
                characterization_summary = self._characterizing(
                    session, run, snapshot, clone_result.workspace
                )
            elif stage is Stage.GENERATING_TESTS:
                assert clone_result is not None and snapshot is not None
                test_generation_summary = self._generating_tests(
                    session, run, snapshot, clone_result.workspace
                )
            elif stage is Stage.EXECUTING:
                assert clone_result is not None and snapshot is not None
                execution_summary = self._executing(session, run, snapshot, clone_result.workspace)
            elif stage is Stage.DETECTING_FAILURES:
                assert clone_result is not None and snapshot is not None and execution_summary is not None
                failure_summary = self._detecting_failures(
                    session, run, snapshot, clone_result.workspace, execution_summary["execution_id"]
                )
            elif stage is Stage.INVESTIGATING:
                assert snapshot is not None
                investigation_summary = self._investigating(session, run, snapshot)
            elif stage is Stage.GENERATING_PATCH:
                assert clone_result is not None and snapshot is not None
                patch_summary = self._generating_patch(session, run, snapshot, clone_result.workspace)
            elif stage is Stage.RANKING_PATCHES:
                self._ranking_patches(session, run)
            elif stage is Stage.VERIFYING_PATCH:
                assert clone_result is not None and snapshot is not None
                verification_summary = self._verifying_patch(session, run, snapshot, clone_result.workspace)
            elif stage is Stage.REGRESSION_VERIFYING:
                self._regression_verifying(session, run, verification_summary)

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
            architecture=architecture_summary,
            git=git_summary,
            archaeology=archaeology_summary,
            understanding=understanding_summary,
            legacy_dna=legacy_dna_summary,
            tech_debt=tech_debt_summary,
            hotspots=hotspot_summary,
            change_safety=change_safety_summary,
            change_impact=change_impact_summary,
            test_discovery=test_discovery_summary,
            characterization=characterization_summary,
            test_generation=test_generation_summary,
            execution=execution_summary,
            failures=failure_summary,
            investigations=investigation_summary,
            patches=patch_summary,
            verification=verification_summary,
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

    def _graph(self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot) -> None:
        result = derive_edges(session, snapshot)
        self._add_evidence(
            session, run, Stage.BUILDING_GRAPH, Classification.FACT,
            f"Module dependency graph: {result.module_graph.number_of_nodes()} modules, "
            f"{result.depends_on_edges} DEPENDS_ON edges, {result.tested_by_edges} TESTED_BY edges",
            produced_by="graph.v1",
            refs={"depends_on": result.depends_on_edges, "tested_by": result.tested_by_edges,
                  "cycles": len(result.cycles)},
        )
        if result.cycles:
            listed = "; ".join(" -> ".join(c) for c in result.cycles[:10])
            self._add_evidence(
                session, run, Stage.BUILDING_GRAPH, Classification.INFERENCE,
                f"{len(result.cycles)} import cycle(s) detected",
                detail=listed, produced_by="graph.v1", confidence=1.0,
                refs={"cycles": result.cycles},
            )

    def _architecture(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
    ) -> dict:
        summary = reconstruct_architecture(session, run, snapshot)
        log.info(
            "architecture stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _git(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
    ) -> dict:
        summary = analyze_git(session, run, snapshot, workspace.resolve_within("repo"))
        log.info("git stage complete", extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}})
        return summary.as_dict()

    def _archaeology(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
    ) -> dict:
        summary = run_archaeology(session, run, snapshot, workspace.resolve_within("repo"))
        log.info(
            "archaeology stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _understanding(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
    ) -> dict:
        summary = run_understanding(session, run, snapshot)
        log.info(
            "understanding stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _legacy_dna(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
    ) -> dict:
        summary = run_legacy_risk(session, run, snapshot)
        log.info(
            "legacy dna stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _tech_debt(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
    ) -> dict:
        summary = run_tech_debt_detection(session, run, snapshot, workspace.resolve_within("repo"))
        log.info(
            "tech debt stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _hotspots(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
    ) -> dict:
        summary = run_hotspot_scoring(session, run, snapshot)
        log.info(
            "hotspots stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _change_safety(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
    ) -> dict:
        summary = run_change_safety(session, run, snapshot)
        log.info(
            "change safety stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _change_impact(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
    ) -> dict:
        summary = run_change_impact(session, run, snapshot)
        log.info(
            "change impact stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _analyzing_tests(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
    ) -> dict:
        summary = discover_existing_tests(session, run, snapshot)
        result = summary.as_dict()
        candidates = identify_untested_components(session, run, snapshot)
        result["untested_candidates"] = len(candidates)
        log.info(
            "test discovery stage complete",
            extra={"extra_fields": {"run_id": run.id, **result}},
        )
        return result

    def _characterizing(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
    ) -> dict:
        summary = run_characterization(session, run, snapshot, workspace)
        log.info(
            "characterization stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _generating_tests(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
    ) -> dict:
        summary = run_test_generation(session, run, snapshot, workspace)
        log.info(
            "test generation stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _executing(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
    ) -> dict:
        summary = run_existing_tests(session, run, snapshot, workspace)
        result = summary.as_dict()
        coverage_text = ""
        if summary.execution_id:
            execution = session.get(Execution, summary.execution_id)
            if execution and execution.coverage_ref:
                artifact = session.get(AnalysisArtifact, execution.coverage_ref)
                if artifact:
                    coverage_text = read_text(artifact)
        gap_summary = analyze_test_gaps(session, run, snapshot, coverage_text)
        result["test_gaps"] = gap_summary.as_dict()
        log.info(
            "execution stage complete",
            extra={"extra_fields": {"run_id": run.id, **result}},
        )
        return result

    def _detecting_failures(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot,
        workspace: Workspace, execution_id: str,
    ) -> dict:
        execution = session.get(Execution, execution_id)
        assert execution is not None
        summary = detect_failures(session, run, snapshot, execution, workspace)
        log.info(
            "failure detection stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _investigating(self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot) -> dict:
        summary = investigate_failures(session, run, snapshot)
        log.info(
            "investigation stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _generating_patch(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
    ) -> dict:
        summary = generate_patches(session, run, snapshot, workspace)
        log.info(
            "patch generation stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _ranking_patches(self, session: Session, run: AnalysisRun) -> None:
        summary = rank_patches(session, run)
        log.info(
            "patch ranking stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )

    def _verifying_patch(
        self, session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
    ) -> dict:
        summary = verify_patches(session, run, snapshot, workspace)
        log.info(
            "patch verification stage complete",
            extra={"extra_fields": {"run_id": run.id, **summary.as_dict()}},
        )
        return summary.as_dict()

    def _regression_verifying(
        self, session: Session, run: AnalysisRun, verification_summary: dict | None
    ) -> None:
        # verify_patches (VERIFYING_PATCH) already ran the regression suite per
        # candidate - this stage finalizes/summarizes that result, per the fixed
        # Stage order, rather than re-running anything.
        verified = bool(verification_summary and verification_summary.get("verified"))
        self._add_evidence(
            session, run, Stage.REGRESSION_VERIFYING, Classification.FACT,
            "Regression verification confirmed a VERIFIED patch" if verified
            else "No patch reached a VERIFIED regression-clean state",
            produced_by="patch_verification.v1", confidence=1.0,
        )

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
