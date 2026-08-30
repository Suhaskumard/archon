"""Request/response models for the API (spec section 47)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from archon.domain.enums import RunMode


class RepositoryCreate(BaseModel):
    url: str = Field(min_length=1, description="github.com URL, owner/repo shorthand, or local path")
    default_branch: str | None = None


class RepositoryOut(BaseModel):
    id: str
    provider: str
    url: str
    owner: str | None
    name: str | None
    default_branch: str | None
    created_at: datetime


class RunCreate(BaseModel):
    ref: str | None = Field(default=None, description="branch, tag or commit sha; default branch if omitted")
    mode: RunMode = RunMode.INGEST_ONLY


class EvidenceOut(BaseModel):
    id: str
    stage: str | None
    classification: str
    summary: str
    detail: str | None
    source_path: str | None
    source_line: int | None
    confidence: float | None
    produced_by: str
    refs: dict | None
    created_at: datetime


class SnapshotOut(BaseModel):
    id: str
    commit_sha: str
    branch: str | None
    requested_ref: str | None
    size_bytes: int
    file_count: int
    commit_count: int
    support_level: str
    support_notes: dict | None
    created_at: datetime


class RunOut(BaseModel):
    id: str
    repository_id: str
    snapshot_id: str | None
    mode: str
    state: str
    current_stage: str | None
    last_completed_stage: str | None
    progress_pct: float
    engine_versions: dict
    error: dict | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    snapshot: SnapshotOut | None = None
    evidence: list[EvidenceOut] = []


class Page(BaseModel):
    total: int
    limit: int
    offset: int
