"""Parse ``git log`` into structured commit records (spec section 24).

Uses the safe ``run_git`` wrapper (arg lists, redacted output). Records are separated by
US/RS control bytes so commit messages cannot break the parser; ``--numstat`` lines follow
each record header.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from archon.core.logging import get_logger
from archon.providers.repo.gitcli import run_git

log = get_logger("archon.analysis.git")

_RS = "\x1e"  # record separator
_US = "\x1f"  # field separator
_PRETTY = f"format:{_RS}%H{_US}%an{_US}%ae{_US}%aI{_US}%cI{_US}%P{_US}%s"

# rename numstat path forms: "old => new", "pre/{old => new}/post"
_RENAME_BRACE = re.compile(r"^(?P<pre>.*)\{(?P<old>.*) => (?P<new>.*)\}(?P<post>.*)$")
_RENAME_PLAIN = re.compile(r"^(?P<old>.*) => (?P<new>.*)$")


@dataclass
class CommitFile:
    path: str
    insertions: int
    deletions: int
    old_path: str | None = None


@dataclass
class CommitRecord:
    sha: str
    author_name: str
    author_email: str
    authored_at: datetime | None
    committed_at: datetime | None
    parents: list[str]
    subject: str
    files: list[CommitFile] = field(default_factory=list)

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def insertions(self) -> int:
        return sum(f.insertions for f in self.files)

    @property
    def deletions(self) -> int:
        return sum(f.deletions for f in self.files)


@dataclass
class HistoryResult:
    commits: list[CommitRecord]
    total_commits: int
    truncated: bool


def _norm_path(raw: str) -> tuple[str, str | None]:
    raw = raw.strip()
    m = _RENAME_BRACE.match(raw)
    if m:
        new = f"{m.group('pre')}{m.group('new')}{m.group('post')}".replace("//", "/")
        old = f"{m.group('pre')}{m.group('old')}{m.group('post')}".replace("//", "/")
        return new.lstrip("/"), old.lstrip("/")
    m = _RENAME_PLAIN.match(raw)
    if m:
        return m.group("new").strip(), m.group("old").strip()
    return raw, None


def _parse_dt(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:  # pragma: no cover - unusual git date output
        return None


def read_history(repo_dir: str | Path, limit: int) -> HistoryResult:
    limit = max(1, int(limit))
    total = 0
    try:
        total = int(
            run_git(["rev-list", "--count", "HEAD"], cwd=repo_dir).stdout.strip() or "0"
        )
    except Exception:  # pragma: no cover - empty repo already rejected upstream
        total = 0

    proc = run_git(
        [
            "log",
            f"--max-count={limit}",
            "--numstat",
            "--no-color",
            "-M",
            f"--pretty={_PRETTY}",
        ],
        cwd=repo_dir,
    )
    records: list[CommitRecord] = []
    for chunk in proc.stdout.split(_RS):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        lines = chunk.split("\n")
        header = lines[0].split(_US)
        if len(header) < 7:
            continue
        sha, an, ae, aiso, ciso, parents, subject = header[:7]
        rec = CommitRecord(
            sha=sha.strip(),
            author_name=an,
            author_email=ae,
            authored_at=_parse_dt(aiso),
            committed_at=_parse_dt(ciso),
            parents=[p for p in parents.split() if p],
            subject=subject,
        )
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            adds, dels, raw_path = parts
            path, old = _norm_path(raw_path)
            rec.files.append(
                CommitFile(
                    path=path,
                    insertions=0 if adds == "-" else int(adds or 0),
                    deletions=0 if dels == "-" else int(dels or 0),
                    old_path=old,
                )
            )
        records.append(rec)

    log.info(
        "git history read",
        extra={"extra_fields": {"commits": len(records), "total": total}},
    )
    return HistoryResult(
        commits=records, total_commits=total or len(records), truncated=total > len(records)
    )
