"""Resolve webhook-reported changed file paths to component ids in a snapshot."""

from __future__ import annotations

from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.db.models import Component, RepositorySnapshot


def _norm(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return str(PurePosixPath(p)) if p else ""


def resolve_changed_components(
    session: Session, snapshot: RepositorySnapshot, changed_paths: list[str] | None
) -> list[str]:
    """Component ids in ``snapshot`` whose ``path`` is one of ``changed_paths``.

    Repo-relative POSIX paths in, component ids out (FILE / MODULE / FUNCTION / METHOD -
    every granularity sharing a changed file path). Deleted files resolve to nothing.
    Empty / ``None`` input returns ``[]``.
    """
    norm = sorted({_norm(p) for p in (changed_paths or []) if _norm(p)})
    if not norm:
        return []
    rows = session.scalars(
        select(Component.id).where(
            Component.snapshot_id == snapshot.id, Component.path.in_(norm)
        )
    ).all()
    return list(rows)
