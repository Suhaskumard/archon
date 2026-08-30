"""Phase 4 - deterministic git history analysis (spec section 24)."""

from archon.analysis.git.history import CommitRecord, HistoryResult, read_history
from archon.analysis.git.metrics import GitStats, compute_git_stats
from archon.analysis.git.persist import GitSummary, analyze_git

__all__ = [
    "CommitRecord",
    "HistoryResult",
    "read_history",
    "GitStats",
    "compute_git_stats",
    "GitSummary",
    "analyze_git",
]
