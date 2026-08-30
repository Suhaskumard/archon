"""Programmatic Alembic entrypoints (spec section 18).

``upgrade()`` is used by the CLI, tests and container start-up so schema management has a
single code path regardless of database backend.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command
from archon.config import get_settings

_ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"


def _config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def upgrade(revision: str = "head") -> None:
    command.upgrade(_config(), revision)


def downgrade(revision: str = "-1") -> None:
    command.downgrade(_config(), revision)


def stamp_head() -> None:
    command.stamp(_config(), "head")


def current() -> None:  # pragma: no cover - diagnostic helper
    command.current(_config(), verbose=True)
