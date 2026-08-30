"""Persist an ExtractionResult into components / dependencies / evidence (spec section 22).

Extraction is keyed to the *snapshot* (immutable): if components already exist for the
snapshot the extractor is not re-run (spec section 53 caching) - the stage just records
that the cached analysis was reused.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from archon.analysis.source.extractor import extract_repository
from archon.analysis.source.model import EXTRACTOR_VERSION, ExtractionResult
from archon.core.logging import get_logger
from archon.db.models import AnalysisRun, Component, Dependency, Evidence, RepositorySnapshot
from archon.domain.enums import Classification, ComponentKind, DependencyKind, Stage

log = get_logger("archon.analysis.source")

_MAX_PARSE_ERROR_EVIDENCE = 25


@dataclass
class SourceSummary:
    reused: bool
    module_count: int
    file_count: int
    component_counts: dict[str, int]
    edge_counts: dict[str, int]
    entrypoint_count: int
    parse_error_count: int
    degraded: bool

    def as_dict(self) -> dict:
        return {
            "reused": self.reused,
            "modules": self.module_count,
            "files": self.file_count,
            "components": self.component_counts,
            "edges": self.edge_counts,
            "entrypoints": self.entrypoint_count,
            "parse_errors": self.parse_error_count,
            "degraded": self.degraded,
        }


def analyze_source(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, repo_dir: Path
) -> SourceSummary:
    already = session.scalar(
        select(func.count(Component.id)).where(Component.snapshot_id == snapshot.id)
    )
    if already:
        return _summary_from_db(session, run, snapshot, reused=True)

    result = extract_repository(repo_dir)
    _write(session, run, snapshot, result)
    _write_evidence(session, run, result)
    session.flush()
    return _summary_from_extraction(result, reused=False)


# --- persistence ---------------------------------------------------------------


def _component_row(snapshot_id: str, comp, *, parent_id: str | None) -> Component:
    attrs = comp.attributes or {}
    return Component(
        snapshot_id=snapshot_id,
        parent_id=parent_id,
        kind=comp.kind,
        name=comp.name,
        qualified_name=comp.qualified_name,
        path=comp.path,
        start_line=comp.start_line,
        end_line=comp.end_line,
        metrics=comp.metrics or {},
        attributes=attrs,
        is_test=bool(attrs.get("is_test")),
        is_entrypoint=bool(attrs.get("is_entrypoint")),
        is_config=bool(attrs.get("is_config")),
    )


def _write(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, result: ExtractionResult
) -> None:
    # idempotency for a re-run of this stage on a snapshot with no components yet
    session.execute(delete(Dependency).where(Dependency.snapshot_id == snapshot.id))
    session.execute(delete(Component).where(Component.snapshot_id == snapshot.id))
    session.flush()

    key_to_id: dict[str, str] = {}
    seen_identity: dict[tuple[str, str], str] = {}

    pending = list(result.components)
    # insert parents before children; a few passes converge quickly
    guard = 0
    while pending and guard < 50:
        guard += 1
        progressed = False
        still: list = []
        for comp in pending:
            if comp.parent_key is not None and comp.parent_key not in key_to_id:
                still.append(comp)
                continue
            identity = (comp.kind.value, comp.qualified_name)
            if identity in seen_identity:
                key_to_id[comp.key] = seen_identity[identity]  # duplicate def - alias it
                progressed = True
                continue
            row = _component_row(
                snapshot.id, comp,
                parent_id=key_to_id.get(comp.parent_key) if comp.parent_key else None,
            )
            session.add(row)
            session.flush()
            key_to_id[comp.key] = row.id
            seen_identity[identity] = row.id
            progressed = True
        pending = still
        if not progressed:
            break
    for comp in pending:  # orphaned parent ref - attach at top level, keep the row
        identity = (comp.kind.value, comp.qualified_name)
        if identity in seen_identity:
            key_to_id[comp.key] = seen_identity[identity]
            continue
        row = _component_row(snapshot.id, comp, parent_id=None)
        session.add(row)
        session.flush()
        key_to_id[comp.key] = row.id
        seen_identity[identity] = row.id

    # CONTAINS edges from the parent tree
    contains = 0
    for comp in result.components:
        if comp.parent_key and comp.parent_key in key_to_id and comp.key in key_to_id:
            session.add(
                Dependency(
                    snapshot_id=snapshot.id, kind=DependencyKind.CONTAINS,
                    src_component_id=key_to_id[comp.parent_key],
                    dst_component_id=key_to_id[comp.key],
                    target_name=comp.qualified_name, resolved=True, external=False,
                )
            )
            contains += 1

    # IMPORTS / CALLS / INHERITS edges
    for edge in result.edges:
        src_id = key_to_id.get(edge.src_key)
        if not src_id:
            continue
        dst_id = key_to_id.get(edge.dst_key) if edge.dst_key else None
        session.add(
            Dependency(
                snapshot_id=snapshot.id, kind=edge.kind,
                src_component_id=src_id, dst_component_id=dst_id,
                target_name=edge.target_name, resolved=dst_id is not None,
                external=edge.external and dst_id is None, source_line=edge.source_line,
                attributes=edge.attributes,
            )
        )
    session.flush()
    log.info(
        "source rows written",
        extra={"extra_fields": {
            "snapshot_id": snapshot.id, "components": len(key_to_id),
            "contains": contains, "edges": len(result.edges),
        }},
    )


def _write_evidence(session: Session, run: AnalysisRun, result: ExtractionResult) -> None:
    counts = result.counts()

    def ev(classification: Classification, summary: str, detail: str | None = None,
           refs: dict | None = None, confidence: float | None = None) -> None:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.ANALYZING_SOURCE, classification=classification,
                summary=summary[:512], detail=detail, produced_by=EXTRACTOR_VERSION,
                confidence=confidence, refs=refs,
            )
        )

    ev(
        Classification.FACT,
        f"Extracted {result.module_count} Python modules "
        f"({counts['components.CLASS']} classes, {counts['components.FUNCTION']} functions, "
        f"{counts['components.METHOD']} methods)",
        detail=", ".join(f"{k}={v}" for k, v in counts.items()),
        refs={"counts": counts},
    )
    ev(
        Classification.FACT,
        f"Dependency edges: {counts['edges.total']} total, {counts['edges.resolved']} "
        f"resolved to a component in this snapshot",
        refs={
            "imports": counts.get("edges.IMPORTS", 0),
            "calls": counts.get("edges.CALLS", 0),
            "inherits": counts.get("edges.INHERITS", 0),
        },
    )
    if result.entrypoints:
        kinds = sorted({e["kind"] for e in result.entrypoints})
        ev(
            Classification.FACT,
            f"Found {len(result.entrypoints)} entry point(s): {', '.join(kinds)}",
            detail="; ".join(f"{e['kind']}:{e['detail']}" for e in result.entrypoints[:20]),
            refs={"entrypoints": result.entrypoints},
        )
    for pe in result.parse_errors[:_MAX_PARSE_ERROR_EVIDENCE]:
        ev(
            Classification.INFERENCE,
            f"Could not parse {pe['path']} (line {pe.get('line')}): {pe['message']}",
            confidence=1.0,
        )
    if result.degraded:
        ev(Classification.INFERENCE, result.degraded_reason or "source analysis degraded",
           confidence=1.0)


# --- summaries ---------------------------------------------------------------


def _summary_from_extraction(result: ExtractionResult, *, reused: bool) -> SourceSummary:
    counts = result.counts()
    return SourceSummary(
        reused=reused,
        module_count=result.module_count,
        file_count=result.file_count,
        component_counts={k.value: counts[f"components.{k.value}"] for k in ComponentKind},
        edge_counts={
            "IMPORTS": counts.get("edges.IMPORTS", 0),
            "CALLS": counts.get("edges.CALLS", 0),
            "INHERITS": counts.get("edges.INHERITS", 0),
            "resolved": counts["edges.resolved"],
            "total": counts["edges.total"],
        },
        entrypoint_count=len(result.entrypoints),
        parse_error_count=len(result.parse_errors),
        degraded=result.degraded,
    )


def _summary_from_db(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, *, reused: bool
) -> SourceSummary:
    rows = session.execute(
        select(Component.kind, func.count(Component.id))
        .where(Component.snapshot_id == snapshot.id)
        .group_by(Component.kind)
    ).all()
    comp_counts = {k.value: 0 for k in ComponentKind}
    for kind, n in rows:
        comp_counts[kind.value if hasattr(kind, "value") else str(kind)] = n

    erows = session.execute(
        select(Dependency.kind, func.count(Dependency.id))
        .where(Dependency.snapshot_id == snapshot.id)
        .group_by(Dependency.kind)
    ).all()
    edge_counts = {"IMPORTS": 0, "CALLS": 0, "INHERITS": 0, "CONTAINS": 0}
    for kind, n in erows:
        edge_counts[kind.value if hasattr(kind, "value") else str(kind)] = n
    resolved = session.scalar(
        select(func.count(Dependency.id)).where(
            Dependency.snapshot_id == snapshot.id, Dependency.resolved.is_(True)
        )
    )
    edge_counts["resolved"] = int(resolved or 0)
    edge_counts["total"] = sum(v for k, v in edge_counts.items() if k != "resolved")

    session.add(
        Evidence(
            run_id=run.id, stage=Stage.ANALYZING_SOURCE, classification=Classification.FACT,
            summary=f"Reused cached source analysis for snapshot {snapshot.id} "
                    f"({sum(comp_counts.values())} components)",
            produced_by=EXTRACTOR_VERSION,
            refs={"components": comp_counts, "edges": edge_counts},
        )
    )
    session.flush()
    return SourceSummary(
        reused=reused,
        module_count=comp_counts.get("MODULE", 0),
        file_count=comp_counts.get("FILE", 0),
        component_counts=comp_counts,
        edge_counts=edge_counts,
        entrypoint_count=0,
        parse_error_count=0,
        degraded=False,
    )
