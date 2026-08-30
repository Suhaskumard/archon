"""Per-path churn / age / co-change from a commit list (spec section 24).

    churn          = sum of insertions + deletions across all commits touching the path
    commit_count   = how many commits touched it (change frequency)
    first_seen     = earliest authored_at that touched it
    last_changed   = latest authored_at that touched it
    age_days       = (anchor - first_seen) in days   (anchor = snapshot ingest time)
    distinct_authors = unique author emails

Co-change: for every commit, each unordered pair of changed paths gets +1; the pair's
``confidence`` = count / min(commit_count of the two paths).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import combinations

from archon.analysis.git.history import CommitRecord

_CO_CHANGE_MAX_FILES = 30  # commits touching more files than this are treated as bulk moves


@dataclass
class GitStats:
    path: str
    churn: int = 0
    commit_count: int = 0
    insertions: int = 0
    deletions: int = 0
    first_seen: datetime | None = None
    last_changed: datetime | None = None
    authors: set[str] = field(default_factory=set)

    def as_metrics(self, anchor: datetime) -> dict:
        age_days = None
        if self.first_seen is not None:
            first = self.first_seen
            if first.tzinfo is None:
                first = first.replace(tzinfo=UTC)
            age_days = max((anchor - first).days, 0)
        return {
            "churn": self.churn,
            "commit_count": self.commit_count,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_changed": self.last_changed.isoformat() if self.last_changed else None,
            "age_days": age_days,
            "distinct_authors": len(self.authors),
        }


@dataclass
class GitAnalysis:
    per_path: dict[str, GitStats]
    co_change: dict[tuple[str, str], int]
    anchor: datetime

    def co_change_confidence(self, a: str, b: str) -> float:
        key = tuple(sorted((a, b)))
        count = self.co_change.get(key, 0)
        if not count:
            return 0.0
        denom = min(
            self.per_path.get(a, GitStats(a)).commit_count or 1,
            self.per_path.get(b, GitStats(b)).commit_count or 1,
        )
        return round(count / denom, 4)


def _touch(stats: GitStats, rec: CommitRecord, adds: int, dels: int) -> None:
    stats.commit_count += 1
    stats.insertions += adds
    stats.deletions += dels
    stats.churn += adds + dels
    if rec.author_email:
        stats.authors.add(rec.author_email)
    when = rec.authored_at or rec.committed_at
    if when is not None:
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if stats.first_seen is None or when < stats.first_seen:
            stats.first_seen = when
        if stats.last_changed is None or when > stats.last_changed:
            stats.last_changed = when


def compute_git_stats(
    commits: list[CommitRecord], anchor: datetime | None = None
) -> GitAnalysis:
    anchor = anchor or datetime.now(UTC)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)

    per_path: dict[str, GitStats] = {}
    co_change: dict[tuple[str, str], int] = {}

    for rec in commits:
        if rec.is_merge:
            continue
        changed_here: set[str] = set()
        for f in rec.files:
            stats = per_path.setdefault(f.path, GitStats(f.path))
            _touch(stats, rec, f.insertions, f.deletions)
            changed_here.add(f.path)
        # co-change: source files only, skip package __init__ noise and bulk commits
        co_paths = sorted(
            p for p in changed_here
            if p.endswith(".py") and not p.endswith("__init__.py")
        )
        if len(co_paths) <= _CO_CHANGE_MAX_FILES:
            for a, b in combinations(co_paths, 2):
                co_change[(a, b)] = co_change.get((a, b), 0) + 1

    return GitAnalysis(per_path=per_path, co_change=co_change, anchor=anchor)
