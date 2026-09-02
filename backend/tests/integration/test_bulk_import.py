"""Phase 13 - repositories.xlsx bulk input (spec section 50)."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select

from archon.db.base import session_scope
from archon.db.models import Job, Repository
from archon.domain.enums import JobState
from archon.reporting.bulk_import import import_repositories_xlsx


def _xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Repository URL", "Branch", "Analysis Mode", "Priority"])
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_mixed_workbook_creates_repos_jobs_and_reports_errors(test_repo):
    data = _xlsx([
        ["https://github.com/psf/requests", "main", "ANALYSIS_ONLY", 10],
        [str(test_repo), None, "FULL", 50],
        ["not a valid repo url at all", None, "ANALYSIS_ONLY", 1],
    ])
    with session_scope() as s:
        results = import_repositories_xlsx(s, data)

    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    assert by_status.get("created") == 2
    assert by_status.get("error") == 1
    err = next(r for r in results if r.status == "error")
    assert err.row == 4

    with session_scope() as s:
        repos = s.scalars(select(Repository)).all()
        jobs = s.scalars(select(Job)).all()
        assert len(repos) == 2
        assert len(jobs) == 2
        assert {j.state for j in jobs} == {JobState.QUEUED}
        assert sorted(j.priority for j in jobs) == [10, 50]


def test_duplicate_row_is_skipped(test_repo):
    data = _xlsx([
        [str(test_repo), None, "ANALYSIS_ONLY", 100],
        [str(test_repo), None, "ANALYSIS_ONLY", 100],  # same repo + config -> dedupe
    ])
    with session_scope() as s:
        results = import_repositories_xlsx(s, data)
    assert [r.status for r in results] == ["created", "skipped"]


def test_missing_required_column_raises():
    wb = Workbook()
    wb.active.append(["Repository URL", "Priority"])  # no Analysis Mode
    buf = BytesIO()
    wb.save(buf)
    with session_scope() as s:
        try:
            import_repositories_xlsx(s, buf.getvalue())
            raise AssertionError("expected a validation error")
        except Exception as exc:  # ArchonError
            assert "missing required column" in str(exc)
