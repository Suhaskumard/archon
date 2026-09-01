"""phase 10 - incident memory: incidents table; investigations gains
cited_incident_ids

Revision ID: 0010_incidents
Revises: 0009_healing
Create Date: 2026-09-01

``investigations`` is fully-derived data (rebuilt every run), so the cleanest way to
add the new ``cited_incident_ids`` column is to drop and recreate the table from
current model metadata - the exact pattern ``0003_architecture.py`` established for
widening ``dependencies``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from archon.db import models  # noqa: F401  register tables on the metadata
from archon.db.base import Base

revision: str = "0010_incidents"
down_revision: str | None = "0009_healing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("incidents",)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[t] for t in _TABLES])
    op.drop_table("investigations")
    Base.metadata.tables["investigations"].create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("investigations")
    Base.metadata.tables["investigations"].create(bind=bind)
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[t] for t in reversed(_TABLES)])
