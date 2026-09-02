"""Deterministic diff between two analysis runs (spec section 45).

Every section is keyed by component ``qualified_name`` rather than ``component_id``:
component ids are snapshot-scoped and change between commits, but a module/function's
qualified name is stable across commits of the same repository (the same reasoning
``incidents/store.py`` uses for its failure signature).
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.db.models import (
    AnalysisRun,
    ChangeAssessment,
    Component,
    Dependency,
    LegacyDNA,
    RiskAssessment,
    TechnicalDebtFinding,
)
from archon.domain.enums import ComponentKind, enum_value

COMPARISON_VERSION = "comparison.v1"

# Ordered worst-last so "did this regress?" is a simple index comparison.
_RISK_ORDER = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
_CHANGE_SAFETY_ORDER = ["SAFE", "CAUTION", "RISKY", "DANGEROUS"]

# Numeric deltas smaller than this are treated as noise (scores are 0-100 floats).
_EPS = 0.05


def _mean(xs: Iterable[float]) -> float | None:
    xs = list(xs)
    return round(sum(xs) / len(xs), 4) if xs else None


def _regressed(order: list[str], base: str | None, head: str | None) -> bool:
    if base is None or head is None or base not in order or head not in order:
        return False
    return order.index(head) > order.index(base)


def _qn_by_id(session: Session, snapshot_id: str) -> dict[str, str]:
    return {
        c.id: c.qualified_name
        for c in session.scalars(
            select(Component).where(Component.snapshot_id == snapshot_id)
        ).all()
    }


# --- sections ----------------------------------------------------------------------------


def _diff_components(session: Session, base_snap: str, head_snap: str) -> dict:
    def modules(sid: str) -> dict[str, Component]:
        return {
            c.qualified_name: c
            for c in session.scalars(
                select(Component).where(
                    Component.snapshot_id == sid, Component.kind == ComponentKind.MODULE
                )
            ).all()
        }

    base, head = modules(base_snap), modules(head_snap)
    added = sorted(set(head) - set(base))
    removed = sorted(set(base) - set(head))
    role_changes = [
        {"qualified_name": qn, "base_role": base[qn].role, "head_role": head[qn].role}
        for qn in sorted(set(base) & set(head))
        if base[qn].role != head[qn].role
    ]
    return {
        "modules_added": added,
        "modules_removed": removed,
        "role_changes": role_changes,
        "module_count_base": len(base),
        "module_count_head": len(head),
    }


def _edge_set(session: Session, snapshot_id: str) -> set[tuple[str, str, str]]:
    qn = _qn_by_id(session, snapshot_id)
    edges: set[tuple[str, str, str]] = set()
    for d in session.scalars(
        select(Dependency).where(Dependency.snapshot_id == snapshot_id)
    ).all():
        src = qn.get(d.src_component_id)
        if src is None:
            continue
        dst = qn.get(d.dst_component_id) if d.dst_component_id else f"ext:{d.target_name}"
        edges.add((src, dst, enum_value(d.kind) or ""))
    return edges


def _diff_dependencies(session: Session, base_snap: str, head_snap: str) -> dict:
    base, head = _edge_set(session, base_snap), _edge_set(session, head_snap)

    def fmt(e: tuple[str, str, str]) -> str:
        return f"{e[0]} -{e[2]}-> {e[1]}"

    return {
        "edges_added": sorted(fmt(e) for e in head - base),
        "edges_removed": sorted(fmt(e) for e in base - head),
        "edge_count_base": len(base),
        "edge_count_head": len(head),
    }


def _legacy_by_qn(session: Session, run_id: str, snapshot_id: str) -> dict[str, LegacyDNA]:
    qn = _qn_by_id(session, snapshot_id)
    out: dict[str, LegacyDNA] = {}
    for r in session.scalars(select(LegacyDNA).where(LegacyDNA.run_id == run_id)).all():
        key = qn.get(r.component_id)
        if key is not None:
            out[key] = r
    return out


def _diff_legacy_dna(
    session: Session, base_run: AnalysisRun, head_run: AnalysisRun
) -> dict:
    base = _legacy_by_qn(session, base_run.id, base_run.snapshot_id)
    head = _legacy_by_qn(session, head_run.id, head_run.snapshot_id)
    common = sorted(set(base) & set(head))

    changed = []
    deltas = []
    regressions = []
    for qn in common:
        b, h = base[qn], head[qn]
        delta = round(h.legacy_risk_score - b.legacy_risk_score, 4)
        deltas.append(delta)
        bc, hc = enum_value(b.category), enum_value(h.category)
        if _regressed(_RISK_ORDER, bc, hc):
            regressions.append(qn)
        if abs(delta) >= _EPS or bc != hc:
            changed.append(
                {
                    "qualified_name": qn,
                    "base_score": round(b.legacy_risk_score, 4),
                    "head_score": round(h.legacy_risk_score, 4),
                    "delta": delta,
                    "base_category": bc,
                    "head_category": hc,
                    "debt_delta": round((h.debt_score or 0.0) - (b.debt_score or 0.0), 4),
                }
            )
    changed.sort(key=lambda c: c["delta"], reverse=True)
    return {
        "added": sorted(set(head) - set(base)),
        "removed": sorted(set(base) - set(head)),
        "changed": changed,
        "mean_legacy_risk_delta": _mean(deltas),
        "risk_category_regressions": regressions,
    }


def _risk_by_qn(session: Session, run_id: str, snapshot_id: str) -> dict[str, RiskAssessment]:
    qn = _qn_by_id(session, snapshot_id)
    out: dict[str, RiskAssessment] = {}
    for r in session.scalars(select(RiskAssessment).where(RiskAssessment.run_id == run_id)).all():
        key = qn.get(r.component_id)
        if key is None:
            continue
        # prefer the legacy-risk engine row if a component has several
        if key not in out or "legacy_risk" in (r.engine_version or ""):
            out[key] = r
    return out


def _diff_risk(session: Session, base_run: AnalysisRun, head_run: AnalysisRun) -> dict:
    base = _risk_by_qn(session, base_run.id, base_run.snapshot_id)
    head = _risk_by_qn(session, head_run.id, head_run.snapshot_id)
    if not base and not head:
        return {"available": False}
    common = sorted(set(base) & set(head))
    changed = []
    deltas = []
    regressions = []
    for qn in common:
        b, h = base[qn], head[qn]
        delta = round(h.score - b.score, 4)
        deltas.append(delta)
        bc, hc = enum_value(b.category), enum_value(h.category)
        if _regressed(_RISK_ORDER, bc, hc):
            regressions.append(qn)
        if abs(delta) >= _EPS or bc != hc:
            changed.append(
                {
                    "qualified_name": qn,
                    "base_score": round(b.score, 4),
                    "head_score": round(h.score, 4),
                    "delta": delta,
                    "base_category": bc,
                    "head_category": hc,
                }
            )
    changed.sort(key=lambda c: c["delta"], reverse=True)
    return {
        "available": True,
        "changed": changed,
        "mean_risk_delta": _mean(deltas),
        "risk_category_regressions": regressions,
    }


def _diff_coverage(
    session: Session, base_run: AnalysisRun, head_run: AnalysisRun
) -> dict:
    base = _legacy_by_qn(session, base_run.id, base_run.snapshot_id)
    head = _legacy_by_qn(session, head_run.id, head_run.snapshot_id)
    common = sorted(set(base) & set(head))
    deltas = []
    worse, better = [], []
    per_component = []
    for qn in common:
        bc = base[qn].coverage
        hc = head[qn].coverage
        if bc is None or hc is None:
            continue
        delta = round(hc - bc, 4)
        deltas.append(delta)
        if delta <= -_EPS:
            worse.append(qn)
        elif delta >= _EPS:
            better.append(qn)
        if abs(delta) >= _EPS:
            per_component.append(
                {"qualified_name": qn, "base_coverage": round(bc, 4),
                 "head_coverage": round(hc, 4), "delta": delta}
            )
    per_component.sort(key=lambda c: c["delta"])
    return {
        "is_proxy": True,  # coverage is the Legacy-DNA proxy value, not a real run
        "mean_coverage_delta": _mean(deltas),
        "components_worse": worse,
        "components_better": better,
        "changed": per_component,
    }


def _debt_key(f: TechnicalDebtFinding, qn: dict[str, str]) -> tuple[str, str, str]:
    return (qn.get(f.component_id or "", "?"), enum_value(f.category) or "", f.location)


def _diff_technical_debt(
    session: Session, base_run: AnalysisRun, head_run: AnalysisRun
) -> dict:
    def by_key(run_id: str, snapshot_id: str) -> dict[tuple[str, str, str], TechnicalDebtFinding]:
        qn = _qn_by_id(session, snapshot_id)
        return {
            _debt_key(f, qn): f
            for f in session.scalars(
                select(TechnicalDebtFinding).where(TechnicalDebtFinding.run_id == run_id)
            ).all()
        }

    base = by_key(base_run.id, base_run.snapshot_id)
    head = by_key(head_run.id, head_run.snapshot_id)

    def render(f: TechnicalDebtFinding, key: tuple[str, str, str]) -> dict:
        return {
            "qualified_name": key[0],
            "category": key[1],
            "location": key[2],
            "severity": enum_value(f.severity),
        }

    def counts(rows: Iterable[TechnicalDebtFinding]) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in rows:
            out[enum_value(f.category) or "?"] = out.get(enum_value(f.category) or "?", 0) + 1
        return out

    added = [render(head[k], k) for k in sorted(set(head) - set(base))]
    resolved = [render(base[k], k) for k in sorted(set(base) - set(head))]
    return {
        "findings_added": added,
        "findings_resolved": resolved,
        "count_base": len(base),
        "count_head": len(head),
        "count_by_category_base": counts(base.values()),
        "count_by_category_head": counts(head.values()),
    }


def _change_safety_by_qn(
    session: Session, run_id: str, snapshot_id: str
) -> dict[str, ChangeAssessment]:
    qn = _qn_by_id(session, snapshot_id)
    out: dict[str, ChangeAssessment] = {}
    for r in session.scalars(
        select(ChangeAssessment).where(ChangeAssessment.run_id == run_id)
    ).all():
        key = qn.get(r.component_id)
        if key is not None:
            out[key] = r
    return out


def _diff_change_safety(
    session: Session, base_run: AnalysisRun, head_run: AnalysisRun
) -> dict:
    base = _change_safety_by_qn(session, base_run.id, base_run.snapshot_id)
    head = _change_safety_by_qn(session, head_run.id, head_run.snapshot_id)
    common = sorted(set(base) & set(head))
    changed = []
    deltas = []
    regressions = []
    for qn in common:
        b, h = base[qn], head[qn]
        # higher safety_score = safer; a drop is a regression
        delta = round(h.safety_score - b.safety_score, 4)
        deltas.append(delta)
        bc, hc = enum_value(b.risk_category), enum_value(h.risk_category)
        if _regressed(_CHANGE_SAFETY_ORDER, bc, hc) or delta <= -_EPS:
            regressions.append(qn)
        if abs(delta) >= _EPS or bc != hc:
            changed.append(
                {
                    "qualified_name": qn,
                    "base_score": round(b.safety_score, 4),
                    "head_score": round(h.safety_score, 4),
                    "delta": delta,
                    "base_category": bc,
                    "head_category": hc,
                }
            )
    changed.sort(key=lambda c: c["delta"])
    return {
        "added": sorted(set(head) - set(base)),
        "removed": sorted(set(base) - set(head)),
        "changed": changed,
        "mean_change_safety_delta": _mean(deltas),
        "change_safety_regressions": sorted(set(regressions)),
    }


# --- orchestration ---------------------------------------------------------------------


def _summarize(report: dict) -> dict:
    arch = report["architecture"]
    deps = report["dependencies"]
    debt = report["technical_debt"]
    return {
        "modules_added": len(arch["modules_added"]),
        "modules_removed": len(arch["modules_removed"]),
        "dependencies_added": len(deps["edges_added"]),
        "dependencies_removed": len(deps["edges_removed"]),
        "debt_findings_added": len(debt["findings_added"]),
        "debt_findings_resolved": len(debt["findings_resolved"]),
        "mean_legacy_risk_delta": report["legacy_dna"]["mean_legacy_risk_delta"],
        "mean_change_safety_delta": report["change_safety"]["mean_change_safety_delta"],
        "mean_coverage_delta": report["coverage"]["mean_coverage_delta"],
        "risk_category_regressions": sorted(
            set(report["legacy_dna"]["risk_category_regressions"])
            | set(report["risk"].get("risk_category_regressions", []))
        ),
        "change_safety_regressions": report["change_safety"]["change_safety_regressions"],
    }


def compute_comparison(
    session: Session, base_run: AnalysisRun, head_run: AnalysisRun
) -> dict:
    """Full delta document for ``base_run`` -> ``head_run``. Both runs must have a
    ``snapshot_id`` (guaranteed by the caller)."""
    base_snap, head_snap = base_run.snapshot_id, head_run.snapshot_id
    assert base_snap and head_snap  # caller guards this

    report: dict = {
        "schema": "archon.comparison.v1",
        "produced_by": COMPARISON_VERSION,
        "base_run_id": base_run.id,
        "head_run_id": head_run.id,
        "base_snapshot_id": base_snap,
        "head_snapshot_id": head_snap,
        "architecture": _diff_components(session, base_snap, head_snap),
        "dependencies": _diff_dependencies(session, base_snap, head_snap),
        "legacy_dna": _diff_legacy_dna(session, base_run, head_run),
        "risk": _diff_risk(session, base_run, head_run),
        "coverage": _diff_coverage(session, base_run, head_run),
        "technical_debt": _diff_technical_debt(session, base_run, head_run),
        "change_safety": _diff_change_safety(session, base_run, head_run),
    }
    report["summary"] = _summarize(report)
    return report
