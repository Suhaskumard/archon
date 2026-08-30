"""Repository providers (spec section 20)."""

from archon.providers.repo.base import (
    CloneResult,
    RepositoryMetadata,
    RepositoryProvider,
    RepositoryRef,
)
from archon.providers.repo.github import GitHubRepositoryProvider
from archon.providers.repo.local import LocalRepositoryProvider

__all__ = [
    "CloneResult",
    "GitHubRepositoryProvider",
    "LocalRepositoryProvider",
    "RepositoryMetadata",
    "RepositoryProvider",
    "RepositoryRef",
    "provider_for",
]


def provider_for(url: str) -> RepositoryProvider:
    """Pick a provider from a raw URL/path (spec section 20).

    GitHub URLs and ``owner/repo`` shorthand -> GitHub; anything that exists on the local
    filesystem -> local. Order matters: an explicit github.com URL always wins.
    """
    from pathlib import Path

    from archon.core.errors import ArchonError, ErrorCode, Recoverability

    raw = url.strip()
    lowered = raw.lower()
    if not raw:
        raise ArchonError(
            ErrorCode.INVALID_REPOSITORY_URL,
            "empty repository reference",
            context={"url": url},
            recoverability=Recoverability.NON_RECOVERABLE,
            suggested_action="Pass a github.com URL, an owner/repo shorthand, or a local path.",
        )
    if "github.com" in lowered or lowered.startswith("git@github.com"):
        return GitHubRepositoryProvider()
    if lowered.startswith("file://"):
        return LocalRepositoryProvider()
    if Path(raw).expanduser().is_dir():
        return LocalRepositoryProvider()
    # ``owner/repo`` shorthand
    stripped = raw.strip("/")
    if stripped.count("/") == 1 and " " not in stripped and ":" not in stripped:
        return GitHubRepositoryProvider()

    raise ArchonError(
        ErrorCode.INVALID_REPOSITORY_URL,
        f"cannot determine a provider for {url!r}",
        context={"url": url},
        recoverability=Recoverability.NON_RECOVERABLE,
        suggested_action="Pass a github.com URL, an owner/repo shorthand, or an existing local path.",
    )
