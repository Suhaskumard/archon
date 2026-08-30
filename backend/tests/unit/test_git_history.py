"""Parsing ``git log --numstat`` output into CommitRecords (spec section 24)."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from archon.analysis.git.history import read_history

_RS = "\x1e"
_US = "\x1f"


def _blob(*records: str) -> str:
    return "".join(records)


def _rec(sha, an, ae, aiso, ciso, parents, subject, numstat: str) -> str:
    header = _RS + _US.join([sha, an, ae, aiso, ciso, parents, subject])
    return header + "\n" + numstat + "\n"


def test_parse_basic_history():
    out = _blob(
        _rec("b" * 40, "Bob", "bob@x.io", "2026-08-01T10:00:00+00:00",
             "2026-08-01T10:00:00+00:00", "a" * 40, "guard qty",
             "12\t3\tpkg/billing.py"),
        _rec("a" * 40, "Ann", "ann@x.io", "2026-06-01T09:00:00+00:00",
             "2026-06-01T09:00:00+00:00", "", "initial",
             "40\t0\tpkg/billing.py\n10\t0\tpkg/calc.py"),
    )
    with patch("archon.analysis.git.history.run_git") as rg:
        rg.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="2\n", stderr=""),      # rev-list --count
            subprocess.CompletedProcess([], 0, stdout=out, stderr=""),        # log
        ]
        result = read_history("/x", limit=100)

    assert result.total_commits == 2 and result.truncated is False
    assert [c.sha for c in result.commits] == ["b" * 40, "a" * 40]
    first = result.commits[0]
    assert first.author_name == "Bob" and first.author_email == "bob@x.io"
    assert first.parents == ["a" * 40] and first.is_merge is False
    assert first.insertions == 12 and first.deletions == 3
    assert first.files[0].path == "pkg/billing.py"
    assert result.commits[1].files[1].path == "pkg/calc.py"


def test_truncation_flag_and_binary_and_rename():
    out = _blob(
        _rec("c" * 40, "Cy", "cy@x.io", "2026-08-02T00:00:00+00:00",
             "2026-08-02T00:00:00+00:00", "p" * 40, "rename + binary",
             "-\t-\tassets/logo.png\n5\t1\tpkg/{old.py => new.py}"),
    )
    with patch("archon.analysis.git.history.run_git") as rg:
        rg.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="9\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout=out, stderr=""),
        ]
        result = read_history("/x", limit=1)
    assert result.truncated is True and result.total_commits == 9
    files = {f.path: f for f in result.commits[0].files}
    assert files["assets/logo.png"].insertions == 0  # binary "-"
    assert "pkg/new.py" in files and files["pkg/new.py"].old_path == "pkg/old.py"


def test_merge_commit_flagged():
    out = _rec("m" * 40, "M", "m@x.io", "2026-08-03T00:00:00+00:00",
               "2026-08-03T00:00:00+00:00", f"{'p'*40} {'q'*40}", "Merge", "")
    with patch("archon.analysis.git.history.run_git") as rg:
        rg.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="1\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout=out, stderr=""),
        ]
        result = read_history("/x", limit=10)
    assert result.commits[0].is_merge is True
