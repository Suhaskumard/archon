"""Persistence for repository comparison (spec section 45).

One ``RepositoryComparison`` row per ordered ``(base_run, head_run)`` pair, plus the
full report written to disk as an ``AnalysisArtifact`` (the spec's "report as
artifact"). Recomputing an existing pair refreshes the row in place - the same
idempotent-upsert convention ``core/artifacts.write_json`` and ``ChangeImpact`` use.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.comparison.differ import COMPARISON_VERSION, compute_comparison
from archon.core.artifacts import write_json
from archon.core.logging import get_logger
from archon.db.models import AnalysisRun, RepositoryComparison

log = get_logger("archon.comparison")


def find_existing_comparison(
    session: Session, base_run_id: str, head_run_id: str
) -> RepositoryComparison | None:
    return session.scalar(
        select(RepositoryComparison).where(
            RepositoryComparison.base_run_id == base_run_id,
            RepositoryComparison.head_run_id == head_run_id,
        )
    )


def build_comparison(
    session: Session,
    repo_id: str,
    base_run: AnalysisRun,
    head_run: AnalysisRun,
    *,
    refresh: bool = False,
) -> RepositoryComparison:
    """Compute (or return the cached) comparison for ``base_run`` -> ``head_run``."""
    existing = find_existing_comparison(session, base_run.id, head_run.id)
    if existing is not None and not refresh:
        return existing

    report = compute_comparison(session, base_run, head_run)

    row = existing or RepositoryComparison(
        repo_id=repo_id, base_run_id=base_run.id, head_run_id=head_run.id
    )
    row.repo_id = repo_id
    row.base_snapshot_id = base_run.snapshot_id
    row.head_snapshot_id = head_run.snapshot_id
    row.base_commit_sha = base_run.snapshot.commit_sha if base_run.snapshot else None
    row.head_commit_sha = head_run.snapshot.commit_sha if head_run.snapshot else None
    row.summary = report["summary"]
    row.report = report
    row.produced_by = COMPARISON_VERSION
    if existing is None:
        session.add(row)
    session.flush()

    art = write_json(session, head_run.id, f"repo_comparison_{row.id}", report)
    row.report_artifact_id = art.id
    session.flush()

    log.info(
        "repository comparison built",
        extra={"extra_fields": {
            "comparison_id": row.id, "base_run_id": base_run.id, "head_run_id": head_run.id,
        }},
    )
    return row
