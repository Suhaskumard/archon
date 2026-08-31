"""Repository Understanding stage runner (spec section 30).

Cheap pure aggregation over rows Phases 2-4 already persisted - no AI, no heavy
computation - so unlike the other three Phase 5 engines this one is never cached across
runs; it always recomputes from the current run's evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archon.analysis.scoring.thresholds import UNDERSTANDING_HISTORY_DEPTH_DAYS
from archon.analysis.scoring.understanding import (
    UNDERSTANDING_VERSION,
    UnderstandingDimensions,
    understanding_score,
)
from archon.core.artifacts import write_json
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    BehaviorReconstruction,
    Commit,
    Component,
    Dependency,
    Evidence,
    RepositorySnapshot,
)
from archon.domain.enums import Classification, ComponentKind, DependencyKind, Stage

log = get_logger("archon.analysis.scoring.understanding")

_ARTIFACT_KIND = "understanding"


@dataclass
class UnderstandingSummary:
    score: float
    confidence: float
    dimensions: dict
    artifact_ref: str | None = None

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "confidence": self.confidence,
            "dimensions": self.dimensions,
            "artifact": self.artifact_ref,
        }


def _fraction(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _compute_dimensions(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
) -> UnderstandingDimensions:
    modules_total = session.scalar(
        select(func.count(Component.id)).where(
            Component.snapshot_id == snapshot.id, Component.kind == ComponentKind.MODULE
        )
    ) or 0
    modules_with_role = session.scalar(
        select(func.count(Component.id)).where(
            Component.snapshot_id == snapshot.id,
            Component.kind == ComponentKind.MODULE,
            Component.role.is_not(None),
        )
    ) or 0

    internal_deps_total = session.scalar(
        select(func.count(Dependency.id)).where(
            Dependency.snapshot_id == snapshot.id, Dependency.external.is_(False)
        )
    ) or 0
    internal_deps_resolved = session.scalar(
        select(func.count(Dependency.id)).where(
            Dependency.snapshot_id == snapshot.id,
            Dependency.external.is_(False),
            Dependency.resolved.is_(True),
        )
    ) or 0

    behavior_targets = session.scalar(
        select(func.count(Component.id)).where(
            Component.snapshot_id == snapshot.id,
            Component.kind.in_(
                [ComponentKind.MODULE, ComponentKind.FUNCTION, ComponentKind.METHOD]
            ),
        )
    ) or 0
    behaviors_done = session.scalar(
        select(func.count(BehaviorReconstruction.id)).where(
            BehaviorReconstruction.run_id == run.id
        )
    ) or 0

    span_days = 0
    first_ts, last_ts = session.execute(
        select(func.min(Commit.authored_at), func.max(Commit.authored_at)).where(
            Commit.snapshot_id == snapshot.id
        )
    ).one()
    if first_ts and last_ts:
        span_days = max((last_ts - first_ts).days, 0)

    testable_modules = session.scalar(
        select(func.count(Component.id)).where(
            Component.snapshot_id == snapshot.id,
            Component.kind == ComponentKind.MODULE,
            Component.is_test.is_(False),
        )
    ) or 0
    tested_modules = session.scalar(
        select(func.count(func.distinct(Dependency.src_component_id))).where(
            Dependency.snapshot_id == snapshot.id,
            Dependency.kind == DependencyKind.TESTED_BY.value,
        )
    ) or 0

    config_total = session.scalar(
        select(func.count(Component.id)).where(
            Component.snapshot_id == snapshot.id, Component.is_config.is_(True)
        )
    ) or 0
    # attributes.parse_error is a JSON key - count in Python (small set, config files only)
    config_ok = 0
    if config_total:
        config_rows = session.scalars(
            select(Component).where(
                Component.snapshot_id == snapshot.id, Component.is_config.is_(True)
            )
        ).all()
        config_ok = sum(1 for c in config_rows if not (c.attributes or {}).get("parse_error"))

    counts = {
        "modules_with_role": modules_with_role, "modules_total": modules_total,
        "internal_deps_resolved": internal_deps_resolved, "internal_deps_total": internal_deps_total,
        "behaviors_done": behaviors_done, "behavior_targets": behavior_targets,
        "history_span_days": span_days,
        "tested_modules": tested_modules, "testable_modules": testable_modules,
        "config_ok": config_ok, "config_total": config_total,
    }
    return UnderstandingDimensions(
        architecture=_fraction(modules_with_role, modules_total),
        dependency=_fraction(internal_deps_resolved, internal_deps_total),
        behavior=_fraction(behaviors_done, behavior_targets),
        historical=round(min(span_days / UNDERSTANDING_HISTORY_DEPTH_DAYS, 1.0), 4)
        if UNDERSTANDING_HISTORY_DEPTH_DAYS else 0.0,
        testing=_fraction(tested_modules, testable_modules),
        configuration=_fraction(config_ok, config_total),
        evidence_counts=counts,
    )


def run_understanding(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot
) -> UnderstandingSummary:
    dims = _compute_dimensions(session, run, snapshot)
    result = understanding_score(dims)

    artifact = write_json(
        session, run.id, _ARTIFACT_KIND,
        {
            "schema": "archon.understanding.v1",
            "run_id": run.id, "snapshot_id": snapshot.id,
            "score": result.score, "confidence": result.confidence,
            "dimensions": result.dimensions, "evidence_coverage": result.evidence_coverage,
        },
        stage=Stage.SCORING_UNDERSTANDING,
    )

    session.add(
        Evidence(
            run_id=run.id, stage=Stage.SCORING_UNDERSTANDING, classification=Classification.INFERENCE,
            summary=f"Repository understanding: {result.score}/100 (confidence {result.confidence})",
            detail=", ".join(f"{k}={v:.2f}" for k, v in result.dimensions.items()),
            produced_by=UNDERSTANDING_VERSION, confidence=result.confidence,
            refs={"dimensions": result.dimensions},
        )
    )
    session.flush()
    log.info(
        "understanding scored",
        extra={"extra_fields": {"run_id": run.id, "score": result.score, "confidence": result.confidence}},
    )
    return UnderstandingSummary(
        score=result.score, confidence=result.confidence, dimensions=result.dimensions,
        artifact_ref=artifact.ref,
    )
