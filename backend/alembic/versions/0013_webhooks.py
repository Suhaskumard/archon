"""phase 19 - push webhooks: webhook_deliveries; analysis_runs gains trigger /
changed_paths and its ``mode`` column drops the RunMode CHECK constraint

Revision ID: 0013_webhooks
Revises: 0012_modernization
Create Date: 2026-09-03

``analysis_runs.mode`` moves from ``_enum(RunMode)`` (VARCHAR + CHECK) to
``EnumString(RunMode)`` (plain VARCHAR) so future RunMode values never need a CHECK
migration - the ``dependencies.kind`` decision. SQLite has no ``ALTER TABLE ... DROP
CONSTRAINT``, so the table is rebuilt: create a temp table from the target model schema,
copy the shared columns, swap. Rows are preserved.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from archon.db import models  # noqa: F401  register tables on the metadata
from archon.db.base import Base

revision: str = "0013_webhooks"
down_revision: str | None = "0012_modernization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("webhook_deliveries",)

_RUN_INDEXES = (
    ("ix_analysis_runs_repository_id", "repository_id"),
    ("ix_analysis_runs_snapshot_id", "snapshot_id"),
    ("ix_analysis_runs_state", "state"),
    ("ix_analysis_runs_config_hash", "config_hash"),
)

# 0012 shape, minus the two new columns. ``mode`` is a plain VARCHAR (no CHECK).
_BASE_COLS = (
    'id VARCHAR(40) NOT NULL PRIMARY KEY',
    'repository_id VARCHAR(40) NOT NULL',
    'snapshot_id VARCHAR(40)',
    'mode VARCHAR(40) NOT NULL',
    'requested_ref VARCHAR(255)',
    'state VARCHAR(40) NOT NULL',
    'current_stage VARCHAR(40)',
    'last_completed_stage VARCHAR(40)',
    'engine_versions JSON NOT NULL',
    'config_hash VARCHAR(64)',
    'progress_pct FLOAT NOT NULL',
    'error JSON',
)
_NEW_COLS = ('"trigger" JSON', 'changed_paths JSON')
_TAIL_COLS = (
    'started_at DATETIME',
    'ended_at DATETIME',
    'created_at DATETIME NOT NULL',
)
_FKS = (
    'FOREIGN KEY(repository_id) REFERENCES repositories (id) ON DELETE CASCADE',
    'FOREIGN KEY(snapshot_id) REFERENCES repository_snapshots (id) ON DELETE SET NULL',
)


def _rebuild_analysis_runs(*, with_new_columns: bool) -> None:
    bind = op.get_bind()
    col_defs = list(_BASE_COLS) + (list(_NEW_COLS) if with_new_columns else []) + list(_TAIL_COLS)
    new_names = [d.split()[0].strip('"') for d in col_defs]
    existing = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(analysis_runs)")}
    # copy only the columns present in both shapes; any new column defaults to NULL
    copy = [n for n in new_names if n in existing]
    quoted = ", ".join(f'"{n}"' if n == "trigger" else n for n in copy)

    bind.exec_driver_sql('DROP TABLE IF EXISTS "_new_analysis_runs"')
    bind.exec_driver_sql(
        f'CREATE TABLE "_new_analysis_runs" ({", ".join(col_defs + list(_FKS))})'
    )
    bind.exec_driver_sql(
        f'INSERT INTO "_new_analysis_runs" ({quoted}) SELECT {quoted} FROM "analysis_runs"'
    )
    op.drop_table("analysis_runs")
    op.rename_table("_new_analysis_runs", "analysis_runs")
    for name, col in _RUN_INDEXES:
        op.create_index(name, "analysis_runs", [col])


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[t] for t in _TABLES])
    _rebuild_analysis_runs(with_new_columns=True)


def downgrade() -> None:
    bind = op.get_bind()
    _rebuild_analysis_runs(with_new_columns=False)
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[t] for t in reversed(_TABLES)])
