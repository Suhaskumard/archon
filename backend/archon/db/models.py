"""SQLAlchemy models.

Phase 1 tables: repositories, repository_snapshots, analysis_runs, analysis_artifacts,
evidence, jobs. Later phases add their own tables via incremental Alembic migrations
(spec section 9). Every analysis-output row carries ``run_id`` for traceability; snapshots
are immutable once written.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from archon.core.ids import new_id
from archon.db.base import Base
from archon.db.types import EnumString
from archon.domain.enums import (
    Classification,
    ComponentKind,
    DependencyKind,
    JobState,
    JobType,
    ProviderKind,
    RunMode,
    RunState,
    Stage,
    SupportLevel,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _enum(py_enum: type) -> SAEnum:
    # native_enum=False -> portable VARCHAR + CHECK constraint on both SQLite and Postgres
    return SAEnum(py_enum, native_enum=False, length=40, validate_strings=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Repository(Base, TimestampMixin):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("provider", "url", name="uq_repository_provider_url"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("repo"))
    provider: Mapped[ProviderKind] = mapped_column(_enum(ProviderKind), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255))
    default_branch: Mapped[str | None] = mapped_column(String(255))

    snapshots: Mapped[list[RepositorySnapshot]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )
    runs: Mapped[list[AnalysisRun]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )


class RepositorySnapshot(Base, TimestampMixin):
    """An immutable pin of a repository at one commit."""

    __tablename__ = "repository_snapshots"
    __table_args__ = (
        UniqueConstraint("repository_id", "commit_sha", name="uq_snapshot_repo_commit"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("snap"))
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(255))
    requested_ref: Mapped[str | None] = mapped_column(String(255))
    workspace_ref: Mapped[str | None] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    commit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    support_level: Mapped[SupportLevel] = mapped_column(
        _enum(SupportLevel), default=SupportLevel.UNSUPPORTED, nullable=False
    )
    support_notes: Mapped[dict | None] = mapped_column(JSON)

    repository: Mapped[Repository] = relationship(back_populates="snapshots")
    runs: Mapped[list[AnalysisRun]] = relationship(back_populates="snapshot")


class AnalysisRun(Base, TimestampMixin):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("run"))
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("repository_snapshots.id", ondelete="SET NULL"), index=True
    )
    mode: Mapped[RunMode] = mapped_column(_enum(RunMode), default=RunMode.INGEST_ONLY, nullable=False)
    requested_ref: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[RunState] = mapped_column(
        _enum(RunState), default=RunState.PENDING, nullable=False, index=True
    )
    current_stage: Mapped[Stage | None] = mapped_column(_enum(Stage))
    last_completed_stage: Mapped[Stage | None] = mapped_column(_enum(Stage))
    engine_versions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    config_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    repository: Mapped[Repository] = relationship(back_populates="runs")
    snapshot: Mapped[RepositorySnapshot | None] = relationship(back_populates="runs")
    artifacts: Mapped[list[AnalysisArtifact]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    job: Mapped[Job | None] = relationship(back_populates="run", uselist=False)


class AnalysisArtifact(Base, TimestampMixin):
    __tablename__ = "analysis_artifacts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("art"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[Stage | None] = mapped_column(_enum(Stage))
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    storage: Mapped[str] = mapped_column(String(16), default="fs", nullable=False)  # db|fs|object
    ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mime: Mapped[str | None] = mapped_column(String(128))

    run: Mapped[AnalysisRun] = relationship(back_populates="artifacts")


class Evidence(Base, TimestampMixin):
    """Central evidence record - every AI/deterministic conclusion links here (spec section 4)."""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ev"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[Stage | None] = mapped_column(_enum(Stage))
    classification: Mapped[Classification] = mapped_column(_enum(Classification), nullable=False)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    source_path: Mapped[str | None] = mapped_column(String(1024))
    source_line: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    produced_by: Mapped[str] = mapped_column(String(128), nullable=False)
    refs: Mapped[dict | None] = mapped_column(JSON)

    run: Mapped[AnalysisRun] = relationship(back_populates="evidence")


class Job(Base, TimestampMixin):
    """Background unit of work for the analysis pipeline (spec section 15)."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_job_idempotency_key"),
        Index("ix_job_claimable", "state", "priority"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("job"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    type: Mapped[JobType] = mapped_column(_enum(JobType), default=JobType.ANALYSIS, nullable=False)
    state: Mapped[JobState] = mapped_column(
        _enum(JobState), default=JobState.QUEUED, nullable=False, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    dedupe_key: Mapped[str | None] = mapped_column(String(128), index=True)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    current_stage: Mapped[Stage | None] = mapped_column(_enum(Stage))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(default=False, nullable=False)
    error: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[AnalysisRun] = relationship(back_populates="job")


class Component(Base, TimestampMixin):
    """A source-code entity: file, module, class, function or method (spec section 22).

    Belongs to a snapshot (not a run) so extraction results are reused across runs of the
    same commit. ``parent_id`` gives the CONTAINS tree; ``metrics`` holds numbers
    (loc, complexity, ...) and ``attributes`` holds flags (is_test, entrypoint, ...).
    """

    __tablename__ = "components"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "kind", "qualified_name", name="uq_component_identity"),
        Index("ix_component_snapshot_kind", "snapshot_id", "kind"),
        Index("ix_component_path", "snapshot_id", "path"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("comp"))
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("repository_snapshots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ComponentKind] = mapped_column(_enum(ComponentKind), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    qualified_name: Mapped[str] = mapped_column(String(512), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # promoted flags (indexable; also mirrored in ``attributes``)
    is_test: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_entrypoint: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_config: Mapped[bool] = mapped_column(default=False, nullable=False)
    role: Mapped[str | None] = mapped_column(String(64))  # filled in Phase 3

    snapshot: Mapped[RepositorySnapshot] = relationship()
    parent: Mapped[Component | None] = relationship(remote_side="Component.id")


class Dependency(Base, TimestampMixin):
    """A directed edge between components (IMPORTS / CALLS / INHERITS ...) (spec section 22).

    ``dst_component_id`` is null when the target could not be resolved to a component in
    this snapshot (e.g. a stdlib/third-party import); ``target_name`` always records the
    raw dotted reference and ``resolved`` says whether the edge landed on a component.
    """

    __tablename__ = "dependencies"
    __table_args__ = (
        Index("ix_dependency_src", "src_component_id", "kind"),
        Index("ix_dependency_dst", "dst_component_id"),
        Index("ix_dependency_snapshot_kind", "snapshot_id", "kind"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("dep"))
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("repository_snapshots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    src_component_id: Mapped[str] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"), nullable=False
    )
    dst_component_id: Mapped[str | None] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE")
    )
    # EnumString (plain VARCHAR): DependencyKind grows each phase - avoid CHECK migrations.
    kind: Mapped[DependencyKind] = mapped_column(EnumString(DependencyKind), nullable=False)
    target_name: Mapped[str] = mapped_column(String(512), nullable=False)
    resolved: Mapped[bool] = mapped_column(default=False, nullable=False)
    external: Mapped[bool] = mapped_column(default=False, nullable=False)
    source_line: Mapped[int | None] = mapped_column(Integer)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    src: Mapped[Component] = relationship(foreign_keys=[src_component_id])
    dst: Mapped[Component | None] = relationship(foreign_keys=[dst_component_id])


class Commit(Base, TimestampMixin):
    """One git commit reachable from a snapshot's HEAD (spec section 24)."""

    __tablename__ = "commits"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "sha", name="uq_commit_snapshot_sha"),
        Index("ix_commit_snapshot_authored", "snapshot_id", "authored_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cmt"))
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("repository_snapshots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sha: Mapped[str] = mapped_column(String(64), nullable=False)
    author_name: Mapped[str | None] = mapped_column(String(255))
    author_email: Mapped[str | None] = mapped_column(String(320))
    authored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str | None] = mapped_column(Text)
    files_changed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    insertions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deletions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_merge: Mapped[bool] = mapped_column(default=False, nullable=False)
    parents: Mapped[list | None] = mapped_column(JSON)
    changed_paths: Mapped[list | None] = mapped_column(JSON)


class Assumption(Base, TimestampMixin):
    """A hidden assumption detected in the source (spec section 26)."""

    __tablename__ = "assumptions"
    __table_args__ = (Index("ix_assumption_run_kind", "run_id", "kind"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("asm"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("repository_snapshots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_id: Mapped[str | None] = mapped_column(
        ForeignKey("components.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False)
    location: Mapped[str | None] = mapped_column(String(1024))  # path:line
    detail: Mapped[str | None] = mapped_column(Text)
    risk: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[str | None] = mapped_column(String(16))
    suggested_test: Mapped[str | None] = mapped_column(Text)
    produced_by: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_ids: Mapped[list | None] = mapped_column(JSON)


class BehaviorReconstruction(Base, TimestampMixin):
    """Reconstructed behaviour + historical intent for one component (spec sections 24-25)."""

    __tablename__ = "behavior_reconstructions"
    __table_args__ = (
        UniqueConstraint("run_id", "component_id", name="uq_behavior_run_component"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("bhv"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("repository_snapshots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_id: Mapped[str] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str | None] = mapped_column(Text)
    historical_context: Mapped[str | None] = mapped_column(Text)
    current_role: Mapped[str | None] = mapped_column(Text)
    inputs: Mapped[list | None] = mapped_column(JSON)
    outputs: Mapped[list | None] = mapped_column(JSON)
    side_effects: Mapped[list | None] = mapped_column(JSON)
    exceptions: Mapped[list | None] = mapped_column(JSON)
    callers: Mapped[list | None] = mapped_column(JSON)
    callees: Mapped[list | None] = mapped_column(JSON)
    tests: Mapped[list | None] = mapped_column(JSON)
    likely_invariants: Mapped[list | None] = mapped_column(JSON)
    git: Mapped[dict | None] = mapped_column(JSON)
    classification: Mapped[str | None] = mapped_column(String(24))
    confidence: Mapped[str | None] = mapped_column(String(16))
    produced_by: Mapped[str] = mapped_column(String(128), nullable=False)


__all__ = [
    "AnalysisArtifact",
    "AnalysisRun",
    "Assumption",
    "BehaviorReconstruction",
    "Commit",
    "Component",
    "Dependency",
    "Evidence",
    "Job",
    "Repository",
    "RepositorySnapshot",
]
