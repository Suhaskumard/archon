"""GitHub repository provider (spec sections 20, 21).

Handles: URL / shorthand parsing, metadata via the GitHub REST API (auth, rate limits,
timeouts, retries, not-found, private), and a secure clone via the git CLI. Credentials
come from ``settings.github_token`` (env only) and are never written to the canonical URL,
logs or errors.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urlparse

import httpx

from archon.config import get_settings
from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.logging import get_logger
from archon.domain.enums import ProviderKind
from archon.providers.repo.base import (
    CloneResult,
    RepositoryMetadata,
    RepositoryProvider,
    RepositoryRef,
)
from archon.providers.repo.gitcli import dir_stats, looks_like_sha, run_git
from archon.workspace.manager import Workspace

log = get_logger("archon.github")

_OWNER_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubRepositoryProvider(RepositoryProvider):
    kind = ProviderKind.GITHUB

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = get_settings()
        self._transport = transport  # tests inject httpx.MockTransport here

    # --- parsing ---------------------------------------------------------------

    def parse(self, url: str, *, ref: str | None = None) -> RepositoryRef:
        raw = url.strip()
        owner = name = None
        embedded_ref: str | None = None

        if raw.startswith("git@github.com:"):
            path = raw.split(":", 1)[1]
            owner, name = self._split_owner_repo(path)
        elif "github.com" in raw:
            parsed = urlparse(raw if "//" in raw else f"https://{raw}")
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) < 2:
                raise self._invalid(url, "expected github.com/<owner>/<repo>")
            owner, name = parts[0], parts[1]
            if len(parts) >= 4 and parts[2] in {"tree", "commit", "blob"}:
                embedded_ref = "/".join(parts[3:])
        elif _OWNER_REPO.match(raw):
            owner, name = self._split_owner_repo(raw)
        else:
            raise self._invalid(url, "not a github.com URL or owner/repo shorthand")

        name = name.removesuffix(".git")
        if not owner or not name:
            raise self._invalid(url, "could not extract owner and repo")

        canonical = f"https://github.com/{owner}/{name}"
        clone_target = f"{canonical}.git"
        token = self._settings.github_token
        if token:
            clone_target = f"https://x-access-token:{token}@github.com/{owner}/{name}.git"

        return RepositoryRef(
            provider=ProviderKind.GITHUB,
            canonical_url=canonical,
            clone_target=clone_target,
            owner=owner,
            name=name,
            requested_ref=ref or embedded_ref,
        )

    @staticmethod
    def _split_owner_repo(path: str) -> tuple[str, str]:
        parts = [p for p in path.strip("/").split("/") if p]
        return (parts[0], parts[1]) if len(parts) >= 2 else ("", "")

    @staticmethod
    def _invalid(url: str, why: str) -> ArchonError:
        return ArchonError(
            ErrorCode.INVALID_REPOSITORY_URL,
            f"invalid GitHub repository reference: {why}",
            context={"url": url},
            recoverability=Recoverability.NON_RECOVERABLE,
            suggested_action="Use https://github.com/<owner>/<repo> or <owner>/<repo>.",
        )

    # --- metadata ------------------------------------------------------------

    def fetch_metadata(self, ref: RepositoryRef) -> RepositoryMetadata:
        api = self._settings.github_api_url.rstrip("/")
        endpoint = f"{api}/repos/{ref.owner}/{ref.name}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "archon",
        }
        if self._settings.github_token:
            headers["Authorization"] = f"Bearer {self._settings.github_token}"

        resp = self._get_with_retry(endpoint, headers)
        self._raise_for_status(resp, ref)
        data = resp.json()
        size_kb = data.get("size")
        return RepositoryMetadata(
            default_branch=data.get("default_branch") or "main",
            is_private=bool(data.get("private")),
            size_bytes=int(size_kb) * 1024 if isinstance(size_kb, int) else None,
            description=data.get("description"),
            extra={"archived": data.get("archived", False), "fork": data.get("fork", False)},
        )

    def _get_with_retry(self, url: str, headers: dict[str, str]) -> httpx.Response:
        attempts = max(1, self._settings.http_max_retries)
        last_exc: Exception | None = None
        for i in range(attempts):
            try:
                with httpx.Client(
                    timeout=self._settings.http_timeout_seconds, transport=self._transport
                ) as client:
                    resp = client.get(url, headers=headers)
                if resp.status_code >= 500:
                    last_exc = None
                    time.sleep(min(2**i, 8))
                    continue
                return resp
            except (httpx.TimeoutException, httpx.TransportError) as exc:  # transient
                last_exc = exc
                time.sleep(min(2**i, 8))
        raise ArchonError(
            ErrorCode.GITHUB_RATE_LIMITED if last_exc is None else ErrorCode.CLONE_FAILED,
            "GitHub API request failed after retries",
            context={"url": url, "error": str(last_exc) if last_exc else "5xx"},
            recoverability=Recoverability.TRANSIENT,
            suggested_action="Retry later; check GitHub status and your network.",
        )

    @staticmethod
    def _raise_for_status(resp: httpx.Response, ref: RepositoryRef) -> None:
        if resp.status_code == 200:
            return
        if resp.status_code == 404:
            raise ArchonError(
                ErrorCode.REPOSITORY_NOT_FOUND,
                f"repository {ref.slug!r} not found",
                context={"slug": ref.slug},
                recoverability=Recoverability.NON_RECOVERABLE,
                suggested_action="Check the name, or set ARCHON_GITHUB_TOKEN if it is private.",
            )
        if resp.status_code == 401:
            raise ArchonError(
                ErrorCode.GITHUB_UNAUTHORIZED,
                "GitHub rejected the access token",
                recoverability=Recoverability.NON_RECOVERABLE,
                suggested_action="Provide a valid ARCHON_GITHUB_TOKEN.",
            )
        if resp.status_code == 403:
            if resp.headers.get("X-RateLimit-Remaining") == "0":
                reset = resp.headers.get("X-RateLimit-Reset")
                raise ArchonError(
                    ErrorCode.GITHUB_RATE_LIMITED,
                    "GitHub API rate limit exceeded",
                    context={"reset_epoch": reset},
                    recoverability=Recoverability.TRANSIENT,
                    suggested_action="Wait for the rate-limit reset or use an authenticated token.",
                )
            raise ArchonError(
                ErrorCode.REPOSITORY_PRIVATE,
                f"access to {ref.slug!r} is forbidden (private or insufficient scope)",
                context={"slug": ref.slug},
                recoverability=Recoverability.NON_RECOVERABLE,
                suggested_action="Use a token with `repo` scope for private repositories.",
            )
        if resp.status_code == 429:
            raise ArchonError(
                ErrorCode.GITHUB_RATE_LIMITED,
                "GitHub API secondary rate limit hit",
                recoverability=Recoverability.TRANSIENT,
                suggested_action="Back off and retry.",
            )
        raise ArchonError(
            ErrorCode.CLONE_FAILED,
            f"unexpected GitHub API status {resp.status_code}",
            context={"status": resp.status_code, "body": resp.text[:500]},
            recoverability=Recoverability.TRANSIENT,
        )

    # --- clone -------------------------------------------------------------

    def clone(self, ref: RepositoryRef, workspace: Workspace) -> CloneResult:
        limits = self._settings.limits
        dest = workspace.resolve_within("repo")

        clone_args = ["clone", "--no-tags"]
        depth = limits.clone_depth
        want_ref = ref.requested_ref
        if depth and not (want_ref and looks_like_sha(want_ref)):
            clone_args += ["--depth", str(depth)]
        if want_ref and not looks_like_sha(want_ref):
            clone_args += ["--branch", want_ref]
        clone_args += [ref.clone_target, str(dest)]

        run_git(clone_args, timeout=float(limits.max_analysis_duration_seconds))

        if want_ref and looks_like_sha(want_ref):
            co = run_git(["checkout", "--detach", want_ref], cwd=dest, check=False)
            if co.returncode != 0:
                run_git(["fetch", "--depth", "1", "origin", want_ref], cwd=dest)
                co2 = run_git(["checkout", "--detach", want_ref], cwd=dest, check=False)
                if co2.returncode != 0:
                    raise ArchonError(
                        ErrorCode.COMMIT_NOT_FOUND,
                        f"commit {want_ref!r} not found",
                        context={"ref": want_ref},
                        recoverability=Recoverability.NON_RECOVERABLE,
                        suggested_action="Pass a commit sha that exists on the default branch.",
                    )

        commit_sha = run_git(["rev-parse", "HEAD"], cwd=dest).stdout.strip()
        branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest).stdout.strip()
        commit_count = int(run_git(["rev-list", "--count", "HEAD"], cwd=dest).stdout.strip() or "0")
        if commit_count == 0:
            raise ArchonError(
                ErrorCode.EMPTY_REPOSITORY,
                "repository has no commits",
                context={"slug": ref.slug},
                recoverability=Recoverability.NON_RECOVERABLE,
            )

        size_bytes, file_count = dir_stats(dest)
        if size_bytes > limits.max_repo_size_bytes:
            raise ArchonError(
                ErrorCode.REPOSITORY_TOO_LARGE,
                "cloned repository exceeds the maximum size",
                context={"size_bytes": size_bytes, "limit_bytes": limits.max_repo_size_bytes},
                recoverability=Recoverability.NON_RECOVERABLE,
                suggested_action="Raise ARCHON_LIMIT_MAX_REPO_SIZE_BYTES or analyse a smaller repo.",
            )

        return CloneResult(
            commit_sha=commit_sha,
            branch=None if branch == "HEAD" else branch,
            workspace=workspace,
            size_bytes=size_bytes,
            file_count=file_count,
            commit_count=commit_count,
        )
