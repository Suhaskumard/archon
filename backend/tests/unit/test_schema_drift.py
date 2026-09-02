"""Guard: the SQLAlchemy models and the Alembic migrations describe the same schema.

The migrations build each table with ``Base.metadata.create_all(tables=[...])`` off the
live model metadata, so a fresh test DB always matches the models - but a *production*
DB that was migrated before a model gained a column/table would silently diverge, since
no later migration re-creates that table. This test catches "a model changed with no
matching migration" by diffing the migrated DB against ``Base.metadata``.
"""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

import archon.db.base as db_base
from archon.db.base import Base

# Structural diffs = a real missed migration. ``modify_type`` / ``modify_default`` /
# ``modify_nullable`` are dropped: SQLite reflects our ``EnumString`` / ``_enum`` VARCHAR
# and boolean columns lossily and reports spurious type/default changes.
_STRUCTURAL = {
    "add_table", "remove_table",
    "add_column", "remove_column",
    "add_constraint", "remove_constraint",
    "add_index", "remove_index",
    "add_fk", "remove_fk",
}


def _op(diff) -> str | None:
    # compare_metadata yields either a tuple (op, ...) or a list of such tuples
    if isinstance(diff, list):
        return None
    return diff[0] if isinstance(diff, tuple) and diff else None


def test_models_match_migrations():
    # conftest._isolated_env already ran migrate.upgrade() on this fresh DB
    with db_base.get_engine().connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"compare_type": True, "render_as_batch": True}
        )
        diffs = compare_metadata(ctx, Base.metadata)

    flat: list = []
    for d in diffs:
        flat.extend(d if isinstance(d, list) else [d])

    structural = [d for d in flat if _op(d) in _STRUCTURAL]
    assert structural == [], (
        "model/migration drift - a model has a table/column/constraint with no "
        f"matching migration:\n{structural}"
    )
