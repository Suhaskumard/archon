"""Local filesystem repository provider (spec section 20).

Used for the acceptance fixture repo and for analysing a checkout that already exists on
the host. The source path is treated as read-only: we clone *from* it into a fresh
workspace so analysis never mutates the original (Principle 11).
"""

from __future__ import annotations

from pathlib import Path

from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.domain.enums import ProviderKind
from archon.providers.repo.base import (
    CloneResult,
    RepositoryMetadata,
    RepositoryProvider,
    RepositoryRef,
)
from archon.providers.repo.gitcli import dir_stats, looks_like_sha, run_git
from archon.workspace.manager import Workspace


class LocalRepositoryProvider(RepositoryProvider):
    kind = ProviderKind.LOCAL

    def parse(self, url: str, *, ref: str | None = None) -> RepositoryRef:
        raw = url.strip()
        if raw.startswith("file://"):
            from urllib.parse import unquote, urlparse
            from urllib.request import url2pathname

            raw = url2pathname(unquote(urlparse(raw).path))
        path = Path(raw).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise ArchonError(
                ErrorCode.INVALID_REPOSITORY_URL,
                f"local path {url!r} is not an existing directory",
                context={"path": str(path)},
                recoverability=Recoverability.NON_RECOVERABLE,
                suggested_action="Pass a path to a local git repository.",
            )
        if not (path / ".git").exists():
            raise ArchonError(
                ErrorCode.NO_GIT_HISTORY,
                f"{url!r} is not a git repository (no .git directory)",
                context={"path": str(path)},
                recoverability=Recoverability.NON_RECOVERABLE,
                suggested_action="Run `git init` and commit, or point at a real repo.",
            )
        return RepositoryRef(
            provider=ProviderKind.LOCAL,
            canonical_url=str(path),
            clone_target=str(path),
            name=path.name,
            requested_ref=ref,
        )

    def fetch_metadata(self, ref: RepositoryRef) -> RepositoryMetadata:
        src = Path(ref.clone_target)
        head = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=src).stdout.strip()
        default_branch = head if head and head != "HEAD" else "main"
        return RepositoryMetadata(default_branch=default_branch, is_private=False)

    def clone(self, ref: RepositoryRef, workspace: Workspace) -> CloneResult:
        src = Path(ref.clone_target)
        dest = workspace.resolve_within("repo")
        # local clone; no network, keeps full history for archaeology phases
        run_git(["clone", "--no-hardlinks", str(src), str(dest)])

        if ref.requested_ref:
            self._checkout(ref.requested_ref, dest)

        commit_sha = run_git(["rev-parse", "HEAD"], cwd=dest).stdout.strip()
        branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest).stdout.strip()
        commit_count = int(
            run_git(["rev-list", "--count", "HEAD"], cwd=dest).stdout.strip() or "0"
        )
        if commit_count == 0:
            raise ArchonError(
                ErrorCode.EMPTY_REPOSITORY,
                "repository has no commits",
                context={"path": str(src)},
                recoverability=Recoverability.NON_RECOVERABLE,
                suggested_action="Analyse a repository with at least one commit.",
            )
        size_bytes, file_count = dir_stats(dest)
        return CloneResult(
            commit_sha=commit_sha,
            branch=None if branch == "HEAD" else branch,
            workspace=workspace,
            size_bytes=size_bytes,
            file_count=file_count,
            commit_count=commit_count,
        )

    @staticmethod
    def _checkout(target: str, dest: Path) -> None:
        proc = run_git(["checkout", "--detach", target], cwd=dest, check=False)
        if proc.returncode != 0:
            code = ErrorCode.COMMIT_NOT_FOUND if looks_like_sha(target) else ErrorCode.BRANCH_NOT_FOUND
            raise ArchonError(
                code,
                f"ref {target!r} not found in repository",
                context={"ref": target, "stderr": proc.stderr.strip()[:500]},
                recoverability=Recoverability.NON_RECOVERABLE,
                suggested_action="Pass an existing branch, tag or commit sha.",
            )
