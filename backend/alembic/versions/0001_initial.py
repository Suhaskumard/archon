"""initial schema - Phase 1 tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-30

The first migration of a greenfield project: it materialises exactly the Phase 1 model
set (repositories, repository_snapshots, analysis_runs, analysis_artifacts, evidence,
jobs) from the SQLAlchemy metadata, so schema and models cannot drift. Later phases add
explicit column/table migrations on top of this baseline.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from archon.db import models  # noqa: F401  register tables on the metadata
from archon.db.base import Base

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "repositories",
    "repository_snapshots",
    "analysis_runs",
    "analysis_artifacts",
    "evidence",
    "jobs",
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[t] for t in _TABLES])


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[t] for t in reversed(_TABLES)])
