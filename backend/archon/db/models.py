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
from archon.domain.enums import (
    Classification,
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


__all__ = [
    "AnalysisArtifact",
    "AnalysisRun",
    "Evidence",
    "Job",
    "Repository",
    "RepositorySnapshot",
]
