"""Churn / age / co-change math (spec section 24)."""

from __future__ import annotations

from datetime import UTC, datetime

from archon.analysis.git.history import CommitFile, CommitRecord
from archon.analysis.git.metrics import compute_git_stats


def _c(sha, when_iso, files, parents="p"):
    return CommitRecord(
        sha=sha, author_name="A", author_email="a@x.io",
        authored_at=datetime.fromisoformat(when_iso), committed_at=None,
        parents=parents.split() if parents else [], subject="s",
        files=[CommitFile(p, i, d) for (p, i, d) in files],
    )


def test_churn_age_authors():
    anchor = datetime(2026, 9, 1, tzinfo=UTC)
    commits = [
        _c("c2", "2026-08-01T00:00:00+00:00", [("pkg/a.py", 5, 2)]),
        _c("c1", "2026-06-01T00:00:00+00:00", [("pkg/a.py", 40, 0), ("pkg/b.py", 10, 0)]),
    ]
    commits[0].author_email = "bob@x.io"
    stats = compute_git_stats(commits, anchor=anchor)
    a = stats.per_path["pkg/a.py"].as_metrics(anchor)
    assert a["commit_count"] == 2
    assert a["churn"] == 47  # 40 + 5 + 2
    assert a["age_days"] == 92  # 2026-06-01 -> 2026-09-01
    assert a["distinct_authors"] == 2
    b = stats.per_path["pkg/b.py"].as_metrics(anchor)
    assert b["commit_count"] == 1 and b["age_days"] == 92


def test_co_change_pairs_and_confidence():
    anchor = datetime(2026, 9, 1, tzinfo=UTC)
    commits = [
        _c("c1", "2026-06-01T00:00:00+00:00", [("pkg/a.py", 1, 0), ("pkg/b.py", 1, 0)]),
        _c("c2", "2026-07-01T00:00:00+00:00", [("pkg/a.py", 1, 0), ("pkg/b.py", 1, 0)]),
        _c("c3", "2026-08-01T00:00:00+00:00", [("pkg/a.py", 1, 0)]),
    ]
    stats = compute_git_stats(commits, anchor=anchor)
    assert stats.co_change[("pkg/a.py", "pkg/b.py")] == 2
    # a has 3 commits, b has 2 -> confidence = 2 / min(3, 2) = 1.0
    assert stats.co_change_confidence("pkg/a.py", "pkg/b.py") == 1.0


def test_init_and_bulk_commit_excluded_from_co_change():
    anchor = datetime(2026, 9, 1, tzinfo=UTC)
    commits = [
        _c("c1", "2026-06-01T00:00:00+00:00",
           [("pkg/__init__.py", 1, 0), ("pkg/a.py", 1, 0), ("README.md", 1, 0)]),
    ]
    stats = compute_git_stats(commits, anchor=anchor)
    # __init__.py and the non-.py README are excluded; only one .py file remains -> no pairs
    assert stats.co_change == {}
    assert "pkg/__init__.py" in stats.per_path  # churn still tracked


def test_merge_commit_skipped():
    anchor = datetime(2026, 9, 1, tzinfo=UTC)
    m = _c("m", "2026-08-01T00:00:00+00:00", [("pkg/a.py", 99, 99)], parents="p q")
    stats = compute_git_stats([m], anchor=anchor)
    assert "pkg/a.py" not in stats.per_path
