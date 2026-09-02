"""Snapshot-scoped result reuse for the scoring engines (spec section 53).

Legacy DNA and Hotspot are pure functions of a snapshot, so a second run over the same
snapshot clones the prior run's rows instead of re-scoring. The "is there a prior run"
lookup is identical across engines and lives here; each engine keeps its own
``_clone_from_prior`` / ``_write_artifact`` because the columns copied and the artifact
schema are model-specific and a fully generic version would be less readable than the
~30 lines it replaced.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.db.models import AnalysisRun


def prior_run_over_snapshot(
    session: Session, run: AnalysisRun, snapshot_id: str, model
) -> str | None:
    """The id of another run that already produced ``model`` rows for this snapshot."""
    return session.scalar(
        select(model.run_id)
        .where(model.snapshot_id == snapshot_id, model.run_id != run.id)
        .limit(1)
    )
