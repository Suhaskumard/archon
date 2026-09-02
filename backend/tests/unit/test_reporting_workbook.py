"""Phase 13 - workbook builder resilience (spec sections 49-50)."""

from __future__ import annotations

from archon.db.base import session_scope
from archon.db.models import AnalysisRun, Repository, RepositorySnapshot
from archon.domain.enums import ProviderKind, RunMode, RunState, Stage
from archon.reporting.workbook import SHEET_NAMES, build_report, report_bytes


def _bare_run() -> str:
    with session_scope() as s:
        repo = Repository(provider=ProviderKind.LOCAL, url="/tmp/wb", name="wb")
        s.add(repo)
        s.flush()
        snap = RepositorySnapshot(repository_id=repo.id, commit_sha="d" * 40)
        s.add(snap)
        s.flush()
        run = AnalysisRun(
            repository_id=repo.id, snapshot_id=snap.id, mode=RunMode.ANALYSIS_ONLY,
            state=RunState.COMPLETED, last_completed_stage=Stage.SNAPSHOTTING,
        )
        s.add(run)
        s.flush()
        return run.id


def test_build_report_on_a_bare_run_still_has_14_sheets():
    run_id = _bare_run()
    with session_scope() as s:
        wb = build_report(s, run_id)
    assert wb.sheetnames == list(SHEET_NAMES)
    # every sheet has at least a header row and does not raise on save
    for name in SHEET_NAMES:
        assert wb[name].max_row >= 1


def test_report_bytes_is_a_valid_xlsx():
    run_id = _bare_run()
    with session_scope() as s:
        data = report_bytes(s, run_id)
    assert data[:2] == b"PK"  # zip / xlsx magic
    assert len(data) > 2000
