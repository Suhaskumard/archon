"""phase 4 - software archaeology tables (commits, assumptions, behavior_reconstructions)

Revision ID: 0004_archaeology
Revises: 0003_architecture
Create Date: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from archon.db import models  # noqa: F401  register tables on the metadata
from archon.db.base import Base

revision: str = "0004_archaeology"
down_revision: str | None = "0003_architecture"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("commits", "assumptions", "behavior_reconstructions")


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[t] for t in _TABLES])


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[t] for t in reversed(_TABLES)])
