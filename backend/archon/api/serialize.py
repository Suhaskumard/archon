"""ORM -> API model conversion helpers."""

from __future__ import annotations

from archon.api.schemas import (
    ComponentOut,
    DependencyOut,
    EvidenceOut,
    RepositoryOut,
    RunOut,
    SnapshotOut,
)
from archon.db.models import (
    AnalysisRun,
    Component,
    Dependency,
    Evidence,
    Repository,
    RepositorySnapshot,
)


def component_out(c: Component) -> ComponentOut:
    return ComponentOut(
        id=c.id,
        snapshot_id=c.snapshot_id,
        parent_id=c.parent_id,
        kind=c.kind.value,
        name=c.name,
        qualified_name=c.qualified_name,
        path=c.path,
        start_line=c.start_line,
        end_line=c.end_line,
        metrics=c.metrics or {},
        attributes=c.attributes or {},
        is_test=c.is_test,
        is_entrypoint=c.is_entrypoint,
        is_config=c.is_config,
        role=c.role,
    )


def dependency_out(d: Dependency) -> DependencyOut:
    return DependencyOut(
        id=d.id,
        kind=d.kind.value,
        src_component_id=d.src_component_id,
        dst_component_id=d.dst_component_id,
        target_name=d.target_name,
        resolved=d.resolved,
        external=d.external,
        source_line=d.source_line,
        attributes=d.attributes or {},
    )


def repository_out(repo: Repository) -> RepositoryOut:
    return RepositoryOut(
        id=repo.id,
        provider=repo.provider.value,
        url=repo.url,
        owner=repo.owner,
        name=repo.name,
        default_branch=repo.default_branch,
        created_at=repo.created_at,
    )


def snapshot_out(snap: RepositorySnapshot) -> SnapshotOut:
    return SnapshotOut(
        id=snap.id,
        commit_sha=snap.commit_sha,
        branch=snap.branch,
        requested_ref=snap.requested_ref,
        size_bytes=snap.size_bytes,
        file_count=snap.file_count,
        commit_count=snap.commit_count,
        support_level=snap.support_level.value,
        support_notes=snap.support_notes,
        created_at=snap.created_at,
    )


def evidence_out(ev: Evidence) -> EvidenceOut:
    return EvidenceOut(
        id=ev.id,
        stage=ev.stage.value if ev.stage else None,
        classification=ev.classification.value,
        summary=ev.summary,
        detail=ev.detail,
        source_path=ev.source_path,
        source_line=ev.source_line,
        confidence=ev.confidence,
        produced_by=ev.produced_by,
        refs=ev.refs,
        created_at=ev.created_at,
    )


def run_out(run: AnalysisRun, *, include_children: bool = True) -> RunOut:
    return RunOut(
        id=run.id,
        repository_id=run.repository_id,
        snapshot_id=run.snapshot_id,
        mode=run.mode.value,
        state=run.state.value,
        current_stage=run.current_stage.value if run.current_stage else None,
        last_completed_stage=run.last_completed_stage.value if run.last_completed_stage else None,
        progress_pct=run.progress_pct,
        engine_versions=run.engine_versions,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        ended_at=run.ended_at,
        snapshot=snapshot_out(run.snapshot) if include_children and run.snapshot else None,
        evidence=(
            [evidence_out(e) for e in sorted(run.evidence, key=lambda x: x.created_at)]
            if include_children
            else []
        ),
    )
