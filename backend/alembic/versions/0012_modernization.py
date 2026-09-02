"""phase 12 - modernization: modernization_recommendations

Revision ID: 0012_modernization
Revises: 0011_comparison
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from archon.db import models  # noqa: F401  register tables on the metadata
from archon.db.base import Base

revision: str = "0012_modernization"
down_revision: str | None = "0011_comparison"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("modernization_recommendations",)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[t] for t in _TABLES])


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[t] for t in reversed(_TABLES)])
