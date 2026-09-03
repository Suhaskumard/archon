"""Programmatic Alembic entrypoints (spec section 18).

``upgrade()`` is used by the CLI, tests and container start-up so schema management has a
single code path regardless of database backend. On PostgreSQL it takes a session-level
advisory lock so N replicas / containers can all run ``db-upgrade`` on start and only one
actually migrates (the rest block, then see head and no-op).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from alembic import command
from archon.config import get_settings
from archon.core.logging import get_logger

log = get_logger("archon.db.migrate")

_ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"
_MIGRATION_LOCK_KEY = 0x4152_4348  # "ARCH"


def _config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


@contextmanager
def _migration_lock():
    url = get_settings().database_url
    if not url.startswith(("postgresql", "postgres")):
        yield  # SQLite dev/test: single writer, nothing to coordinate
        return
    engine = create_engine(url)
    conn = engine.connect()
    try:
        conn.exec_driver_sql(f"SELECT pg_advisory_lock({_MIGRATION_LOCK_KEY})")
        log.info("acquired migration advisory lock")
        yield
    finally:
        try:
            conn.exec_driver_sql(f"SELECT pg_advisory_unlock({_MIGRATION_LOCK_KEY})")
        finally:
            conn.close()
            engine.dispose()


def upgrade(revision: str = "head") -> None:
    with _migration_lock():
        command.upgrade(_config(), revision)


def head_revision() -> str | None:
    """The latest migration revision defined on disk."""
    return ScriptDirectory.from_config(_config()).get_current_head()


def current_revision() -> str | None:
    """The revision the target database is actually stamped at (None if un-migrated)."""
    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def is_up_to_date() -> bool:
    return current_revision() == head_revision()


def downgrade(revision: str = "-1") -> None:
    command.downgrade(_config(), revision)


def stamp_head() -> None:
    command.stamp(_config(), "head")


def current() -> None:  # pragma: no cover - diagnostic helper
    command.current(_config(), verbose=True)
