"""phase 6 - change safety and change impact

Revision ID: 0006_change_safety
Revises: 0005_scoring
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from archon.db import models  # noqa: F401  register tables on the metadata
from archon.db.base import Base

revision: str = "0006_change_safety"
down_revision: str | None = "0005_scoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("change_assessments", "change_impacts")


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[t] for t in _TABLES])


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[t] for t in reversed(_TABLES)])
