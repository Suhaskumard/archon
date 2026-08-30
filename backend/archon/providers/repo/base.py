"""Repository provider contract (spec section 20).

    parse(url)               -> RepositoryRef            (deterministic, no I/O)
    fetch_metadata(ref)      -> RepositoryMetadata       (network for GitHub)
    clone(ref, workspace)    -> CloneResult              (secure clone + snapshot facts)
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from archon.domain.enums import ProviderKind
from archon.workspace.manager import Workspace


@dataclass(frozen=True)
class RepositoryRef:
    provider: ProviderKind
    canonical_url: str          # what we persist / display (never contains credentials)
    clone_target: str           # what we hand to ``git clone`` (local path or https URL)
    owner: str | None = None
    name: str | None = None
    requested_ref: str | None = None  # branch, tag or commit sha; None -> default branch

    @property
    def slug(self) -> str:
        if self.owner and self.name:
            return f"{self.owner}/{self.name}"
        return self.name or self.canonical_url


@dataclass(frozen=True)
class RepositoryMetadata:
    default_branch: str
    is_private: bool = False
    size_bytes: int | None = None
    description: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CloneResult:
    commit_sha: str
    branch: str | None
    workspace: Workspace
    size_bytes: int
    file_count: int
    commit_count: int


class RepositoryProvider(abc.ABC):
    kind: ProviderKind

    @abc.abstractmethod
    def parse(self, url: str, *, ref: str | None = None) -> RepositoryRef: ...

    @abc.abstractmethod
    def fetch_metadata(self, ref: RepositoryRef) -> RepositoryMetadata: ...

    @abc.abstractmethod
    def clone(self, ref: RepositoryRef, workspace: Workspace) -> CloneResult: ...
