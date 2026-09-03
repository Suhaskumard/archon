"""assess_support language breakdown + PARTIALLY_SUPPORTED for a polyglot repo (Phase 20)."""

from __future__ import annotations

from archon.domain.enums import SupportLevel
from archon.pipeline.support import assess_support


def test_polyglot_repo_is_partially_supported_with_language_breakdown(polyglot_repo):
    a = assess_support(polyglot_repo, commit_count=2)
    assert a.level is SupportLevel.PARTIALLY_SUPPORTED
    assert a.python_file_count >= 1
    assert a.non_python_file_count >= 4
    assert "Python" in a.language_breakdown
    assert set(a.non_python_languages) >= {"JavaScript", "Go"}
    assert a.python_ratio < 0.5
    assert any("non-Python" in r or "50%" in r for r in a.reasons)
    notes = a.as_notes()
    assert notes["non_python_file_count"] == a.non_python_file_count
    assert notes["language_breakdown"]["Python"] == a.python_file_count


def test_pure_python_repo_stays_supported(test_repo):
    a = assess_support(test_repo, commit_count=3)
    assert a.level is SupportLevel.SUPPORTED
    assert a.non_python_languages == {}
    assert a.language_breakdown.get("Python", 0) > 0


def test_shallow_history_is_flagged(polyglot_repo):
    a = assess_support(polyglot_repo, commit_count=1)
    assert a.has_git_history is False
    assert any("history" in r for r in a.reasons)
