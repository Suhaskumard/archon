"""phase 3 - architecture: dependencies.kind -> plain VARCHAR

Revision ID: 0003_architecture
Revises: 0002_source_intelligence
Create Date: 2026-08-30

``dependencies`` is fully-derived data (rebuilt from ``components`` every run), so the
cleanest way to drop the old ``DependencyKind`` CHECK constraint and widen the column to a
plain VARCHAR is to drop and recreate the table from the current model metadata. Existing
snapshots re-populate their edges on the next analysis run (the source-stage cache now also
checks for dependency rows).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from archon.db import models  # noqa: F401  register tables on the metadata
from archon.db.base import Base

revision: str = "0003_architecture"
down_revision: str | None = "0002_source_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    op.drop_table("dependencies")
    Base.metadata.tables["dependencies"].create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("dependencies")
    Base.metadata.tables["dependencies"].create(bind=bind)
