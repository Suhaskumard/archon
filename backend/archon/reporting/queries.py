"""Shared read layer for the Excel report (spec section 49: "sourced from the same
service/domain layer as the API, no separate engine").

Every function here calls the corresponding API router function directly with all
arguments passed explicitly (FastAPI ``Query`` defaults only apply through the request
layer). The report therefore renders exactly what ``GET /runs/{id}/<resource>`` returns.
The three artifact-backed resources (understanding, architecture, evolution) raise
``ArchonError`` when their stage has not run - those are caught and returned as ``None``
so a partial run still produces a workbook.
"""

from __future__ import annotations

import importlib
from functools import cache
from typing import Any

from sqlalchemy.orm import Session

from archon.core.errors import ArchonError


@cache
def _r(name: str):
    """Lazily import a router module (avoids a reporting <-> api import cycle)."""
    return importlib.import_module(f"archon.api.routers.{name}")


def _safe(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except ArchonError:
        return None


def run_overview(session: Session, run_id: str):
    return _r("runs").get_run(run_id, session=session)


def evidence(session: Session, run_id: str):
    return _r("runs").get_run_evidence(run_id, session=session)


def source_summary(session: Session, run_id: str):
    return _safe(_r("source").run_source_summary, run_id, session=session)


def understanding(session: Session, run_id: str):
    return _safe(_r("scoring").get_understanding, run_id, session=session)


def architecture_report(session: Session, run_id: str):
    return _safe(_r("architecture").get_architecture, run_id, session=session)


def evolution(session: Session, run_id: str):
    return _safe(_r("archaeology").get_evolution, run_id, session=session)


def behavior(session: Session, run_id: str):
    return _safe(
        _r("archaeology").list_behavior, run_id, session=session, q=None, limit=1000, offset=0
    ) or []


def assumptions(session: Session, run_id: str):
    return _safe(
        _r("archaeology").list_assumptions, run_id, session=session,
        kind=None, risk=None, component_id=None, limit=2000, offset=0,
    ) or []


def legacy_dna(session: Session, run_id: str):
    return _safe(
        _r("scoring").list_legacy_dna, run_id, session=session,
        category=None, component_id=None, limit=2000, offset=0,
    ) or []


def hotspots(session: Session, run_id: str):
    return _safe(
        _r("scoring").list_hotspots, run_id, session=session,
        classification=None, limit=2000, offset=0,
    ) or []


def technical_debt(session: Session, run_id: str):
    return _safe(
        _r("scoring").list_technical_debt, run_id, session=session,
        category=None, severity=None, component_id=None, limit=5000, offset=0,
    ) or []


def change_safety(session: Session, run_id: str):
    return _safe(
        _r("scoring").list_change_safety, run_id, session=session,
        risk_category=None, component_id=None, limit=2000, offset=0,
    ) or []


def test_gaps(session: Session, run_id: str):
    return _safe(
        _r("execution").list_test_gaps, run_id, session=session,
        priority=None, limit=2000, offset=0,
    ) or []


def characterization(session: Session, run_id: str):
    return _safe(
        _r("execution").list_characterization, run_id, session=session, limit=2000, offset=0
    ) or []


def executions(session: Session, run_id: str):
    return _safe(
        _r("execution").list_executions, run_id, session=session, kind=None, limit=1000, offset=0
    ) or []


def failures(session: Session, run_id: str):
    return _safe(
        _r("healing").list_failures, run_id, session=session, limit=2000, offset=0
    ) or []


def investigations(session: Session, run_id: str):
    return _safe(
        _r("healing").list_investigations, run_id, session=session, limit=2000, offset=0
    ) or []


def patches(session: Session, run_id: str):
    return _safe(
        _r("healing").list_patches, run_id, session=session, state=None, limit=2000, offset=0
    ) or []


def verifications(session: Session, run_id: str):
    return _safe(
        _r("healing").list_verifications, run_id, session=session, limit=2000, offset=0
    ) or []


def incidents_for_run(session: Session, run_id: str):
    return _safe(
        _r("incidents").list_run_incidents, run_id, session=session, limit=2000, offset=0
    ) or []


def modernization(session: Session, run_id: str):
    return _safe(
        _r("modernization").list_modernization, run_id, session=session,
        strategy=None, limit=2000, offset=0,
    ) or []
