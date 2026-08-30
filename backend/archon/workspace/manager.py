"""Workspace manager (spec sections 11, 12, 52).

A workspace is a disposable directory under ``settings.resolved_workspace_root`` that holds
one repository checkout. Guarantees:

* every workspace path stays inside the configured root (path-traversal safe);
* a total-quota check runs before a new workspace is created;
* ``cleanup`` always removes the tree, even on Windows read-only files;
* nothing here ever executes repository code - that is the sandbox's job.
"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from archon.config import Settings, get_settings
from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.ids import new_id
from archon.core.logging import get_logger

log = get_logger("archon.workspace")


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            try:
                total += fp.stat().st_size
            except OSError:  # pragma: no cover - race on cleanup
                pass
    return total


def _on_rm_error(func, path, _exc):  # pragma: no cover - windows read-only glue
    os.chmod(path, stat.S_IWRITE)
    func(path)


@dataclass(frozen=True)
class Workspace:
    id: str
    path: Path

    def resolve_within(self, relative: str) -> Path:
        """Resolve ``relative`` against the workspace, refusing to escape it."""
        candidate = (self.path / relative).resolve()
        root = self.path.resolve()
        if candidate != root and root not in candidate.parents:
            raise ArchonError(
                ErrorCode.PATH_TRAVERSAL,
                "path escapes the workspace root",
                context={"workspace": str(root), "attempted": str(candidate)},
                recoverability=Recoverability.NON_RECOVERABLE,
                suggested_action="Use a relative path that stays inside the workspace.",
            )
        return candidate

    def size_bytes(self) -> int:
        return _dir_size(self.path)


class WorkspaceManager:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self.root = self._settings.resolved_workspace_root
        self.root.mkdir(parents=True, exist_ok=True)

    def _quota_check(self) -> None:
        used = _dir_size(self.root)
        quota = self._settings.workspace_quota_bytes
        if used >= quota:
            raise ArchonError(
                ErrorCode.WORKSPACE_QUOTA_EXCEEDED,
                "workspace storage quota exhausted",
                context={"used_bytes": used, "quota_bytes": quota},
                recoverability=Recoverability.RECOVERABLE,
                suggested_action="Wait for running analyses to finish or raise ARCHON_WORKSPACE_QUOTA_BYTES.",
            )

    def create(self, label: str = "ws") -> Workspace:
        self._quota_check()
        ws_id = new_id(label)
        path = (self.root / ws_id).resolve()
        if self.root.resolve() not in path.parents:
            raise ArchonError(
                ErrorCode.PATH_TRAVERSAL,
                "computed workspace path is outside the root",
                context={"root": str(self.root), "path": str(path)},
            )
        path.mkdir(parents=True, exist_ok=False)
        log.info("workspace created", extra={"extra_fields": {"workspace_id": ws_id}})
        return Workspace(id=ws_id, path=path)

    def cleanup(self, workspace: Workspace) -> None:
        if workspace.path.exists():
            shutil.rmtree(workspace.path, onerror=_on_rm_error)
            log.info("workspace removed", extra={"extra_fields": {"workspace_id": workspace.id}})

    @contextmanager
    def scoped(self, label: str = "ws") -> Iterator[Workspace]:
        ws = self.create(label)
        try:
            yield ws
        finally:
            self.cleanup(ws)

    def reap_orphans(self) -> int:
        """Remove any workspace directory left behind by a crashed worker."""
        removed = 0
        for child in self.root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, onerror=_on_rm_error)
                removed += 1
        if removed:
            log.info("reaped orphan workspaces", extra={"extra_fields": {"count": removed}})
        return removed
