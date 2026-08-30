"""Persist git analysis: commits, per-component git metrics, CHANGED_WITH / CHANGED_BY.

Keyed to the snapshot (immutable). Idempotent: a re-run clears the snapshot's commits and
its CHANGED_WITH / CHANGED_BY edges before rewriting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from archon.analysis.git.history import read_history
from archon.analysis.git.metrics import compute_git_stats
from archon.config import get_settings
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Commit,
    Component,
    Dependency,
    Evidence,
    RepositorySnapshot,
)
from archon.domain.enums import Classification, ComponentKind, DependencyKind, Stage

log = get_logger("archon.analysis.git")

GIT_VERSION = "git.v1"
_MAX_CHANGED_BY_PER_COMPONENT = 20
_MAX_CHANGED_WITH_EDGES = 2000


@dataclass
class GitSummary:
    reused: bool
    commits: int
    total_commits: int
    span_days: int
    authors: int
    changed_with_edges: int
    changed_by_edges: int
    truncated: bool
    top_churn: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "reused": self.reused,
            "commits": self.commits,
            "total_commits": self.total_commits,
            "span_days": self.span_days,
            "authors": self.authors,
            "changed_with_edges": self.changed_with_edges,
            "changed_by_edges": self.changed_by_edges,
            "truncated": self.truncated,
            "top_churn": self.top_churn,
        }


def _representative(
    by_path: dict[str, list[Component]], path: str, *, module_only: bool = False
) -> Component | None:
    comps = by_path.get(path)
    if not comps:
        return None
    for c in comps:
        if c.kind is ComponentKind.MODULE:
            return c
    return None if module_only else comps[0]


def analyze_git(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, repo_dir: Path
) -> GitSummary:
    have_commits = session.scalar(
        select(func.count(Commit.id)).where(Commit.snapshot_id == snapshot.id)
    )
    have_metrics = session.scalar(
        select(func.count(Component.id)).where(
            Component.snapshot_id == snapshot.id,
            Component.kind == ComponentKind.MODULE,
        )
    )
    sample = session.scalar(
        select(Component).where(
            Component.snapshot_id == snapshot.id, Component.kind == ComponentKind.MODULE
        )
    )
    cached = bool(have_commits) and bool(sample) and "git" in (sample.metrics or {})
    if cached and have_metrics:
        return _summary_from_db(session, run, snapshot, reused=True)

    limits = get_settings().limits
    history = read_history(repo_dir, limits.max_git_history_commits)
    analysis = compute_git_stats(history.commits, anchor=snapshot.created_at)

    # --- wipe + rewrite commits ---
    session.execute(delete(Commit).where(Commit.snapshot_id == snapshot.id))
    session.execute(
        delete(Dependency).where(
            Dependency.snapshot_id == snapshot.id,
            Dependency.kind.in_(
                [DependencyKind.CHANGED_WITH.value, DependencyKind.CHANGED_BY.value]
            ),
        )
    )
    session.flush()

    sha_to_commit_id: dict[str, str] = {}
    for rec in history.commits:
        row = Commit(
            repository_id=snapshot.repository_id,
            snapshot_id=snapshot.id,
            sha=rec.sha,
            author_name=rec.author_name,
            author_email=rec.author_email,
            authored_at=rec.authored_at,
            committed_at=rec.committed_at,
            message=rec.subject,
            files_changed=len(rec.files),
            insertions=rec.insertions,
            deletions=rec.deletions,
            is_merge=rec.is_merge,
            parents=rec.parents,
            changed_paths=[f.path for f in rec.files],
        )
        session.add(row)
        session.flush()
        sha_to_commit_id[rec.sha] = row.id

    # --- component index by path ---
    comps = session.scalars(
        select(Component).where(Component.snapshot_id == snapshot.id)
    ).all()
    by_path: dict[str, list[Component]] = {}
    for c in comps:
        by_path.setdefault(c.path, []).append(c)

    # --- per-component git metrics ---
    for path, stats in analysis.per_path.items():
        metrics = stats.as_metrics(analysis.anchor)
        for c in by_path.get(path, []):
            m = dict(c.metrics or {})
            m["git"] = metrics
            c.metrics = m

    # --- CHANGED_WITH edges (module-level) ---
    changed_with = 0
    for (pa, pb), count in sorted(
        analysis.co_change.items(), key=lambda kv: kv[1], reverse=True
    ):
        if changed_with >= _MAX_CHANGED_WITH_EDGES:
            break
        ca = _representative(by_path, pa, module_only=True)
        cb = _representative(by_path, pb, module_only=True)
        if ca is None or cb is None or ca.id == cb.id:
            continue
        conf = analysis.co_change_confidence(pa, pb)
        for src, dst in ((ca, cb), (cb, ca)):
            session.add(
                Dependency(
                    snapshot_id=snapshot.id,
                    kind=DependencyKind.CHANGED_WITH,
                    src_component_id=src.id,
                    dst_component_id=dst.id,
                    target_name=dst.qualified_name,
                    resolved=True,
                    external=False,
                    attributes={"count": count, "confidence": conf},
                )
            )
            changed_with += 1

    # --- CHANGED_BY edges ---
    changed_by = 0
    recent_by_path: dict[str, list] = {}
    for rec in history.commits:
        for f in rec.files:
            recent_by_path.setdefault(f.path, []).append((rec, f))
    for path, entries in recent_by_path.items():
        comp = _representative(by_path, path)
        if comp is None:
            continue
        for rec, f in entries[:_MAX_CHANGED_BY_PER_COMPONENT]:
            session.add(
                Dependency(
                    snapshot_id=snapshot.id,
                    kind=DependencyKind.CHANGED_BY,
                    src_component_id=comp.id,
                    dst_component_id=None,
                    target_name=rec.sha,
                    resolved=False,
                    external=False,
                    attributes={
                        "commit_id": sha_to_commit_id.get(rec.sha),
                        "insertions": f.insertions,
                        "deletions": f.deletions,
                        "authored_at": rec.authored_at.isoformat() if rec.authored_at else None,
                        "subject": rec.subject[:200],
                    },
                )
            )
            changed_by += 1

    session.flush()
    summary = _build_summary(
        history, analysis, by_path, changed_with, changed_by, reused=False
    )
    _emit_evidence(session, run, summary)
    log.info("git analysis persisted", extra={"extra_fields": summary.as_dict()})
    return summary


# --- summaries / evidence ----------------------------------------------------------


def _span_days(analysis) -> int:
    firsts = [s.first_seen for s in analysis.per_path.values() if s.first_seen]
    lasts = [s.last_changed for s in analysis.per_path.values() if s.last_changed]
    if not firsts or not lasts:
        return 0
    return max((max(lasts) - min(firsts)).days, 0)


def _build_summary(history, analysis, by_path, changed_with, changed_by, *, reused):
    authors = {
        a for s in analysis.per_path.values() for a in s.authors
    }
    top_churn = sorted(
        (
            {"path": p, "churn": s.churn, "commits": s.commit_count}
            for p, s in analysis.per_path.items()
            if p in by_path
        ),
        key=lambda d: d["churn"],
        reverse=True,
    )[:8]
    return GitSummary(
        reused=reused,
        commits=len(history.commits),
        total_commits=history.total_commits,
        span_days=_span_days(analysis),
        authors=len(authors),
        changed_with_edges=changed_with,
        changed_by_edges=changed_by,
        truncated=history.truncated,
        top_churn=top_churn,
    )


def _emit_evidence(session: Session, run: AnalysisRun, s: GitSummary) -> None:
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.ANALYZING_GIT, classification=Classification.FACT,
            summary=(
                f"Analyzed {s.commits} commit(s) over {s.span_days} day(s) "
                f"({s.authors} author(s)); {s.changed_with_edges} co-change edge(s)"
            ),
            detail="top churn: "
            + ", ".join(f"{c['path']} ({c['churn']})" for c in s.top_churn[:5]),
            produced_by=GIT_VERSION, confidence=1.0,
            refs={"top_churn": s.top_churn},
        )
    )
    if s.truncated:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.ANALYZING_GIT, classification=Classification.INFERENCE,
                summary=(
                    f"Git history truncated to {s.commits} of {s.total_commits} commits; "
                    "older churn/age is undercounted"
                ),
                produced_by=GIT_VERSION, confidence=1.0,
            )
        )
    session.flush()


def _summary_from_db(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, *, reused: bool
) -> GitSummary:
    total = session.scalar(
        select(func.count(Commit.id)).where(Commit.snapshot_id == snapshot.id)
    )
    authors = session.scalar(
        select(func.count(func.distinct(Commit.author_email))).where(
            Commit.snapshot_id == snapshot.id
        )
    )
    cw = session.scalar(
        select(func.count(Dependency.id)).where(
            Dependency.snapshot_id == snapshot.id,
            Dependency.kind == DependencyKind.CHANGED_WITH,
        )
    )
    cb = session.scalar(
        select(func.count(Dependency.id)).where(
            Dependency.snapshot_id == snapshot.id,
            Dependency.kind == DependencyKind.CHANGED_BY,
        )
    )
    session.add(
        Evidence(
            run_id=run.id, stage=Stage.ANALYZING_GIT, classification=Classification.FACT,
            summary=f"Reused cached git analysis for snapshot {snapshot.id} ({total} commits)",
            produced_by=GIT_VERSION,
        )
    )
    session.flush()
    return GitSummary(
        reused=reused, commits=int(total or 0), total_commits=int(total or 0),
        span_days=0, authors=int(authors or 0), changed_with_edges=int(cw or 0),
        changed_by_edges=int(cb or 0), truncated=False,
    )
