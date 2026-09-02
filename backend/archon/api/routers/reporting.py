"""Excel reporting + bulk-input endpoints (spec sections 49-50)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from archon.api.deps import get_session
from archon.core.errors import ArchonError, ErrorCode
from archon.db.models import AnalysisRun
from archon.reporting import bulk_import
from archon.reporting.workbook import REPORT_FILENAME, REPORT_MIME, report_bytes

router = APIRouter(tags=["reporting"])


@router.get("/runs/{run_id}/report.xlsx")
def download_report(run_id: str, session: Session = Depends(get_session)) -> Response:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"run {run_id!r} not found")
    if run.snapshot_id is None:
        raise ArchonError(
            ErrorCode.CONFLICT, "run has no snapshot yet",
            suggested_action="Wait for the run to reach SNAPSHOTTING.",
        )
    data = report_bytes(session, run_id)
    return Response(
        content=data,
        media_type=REPORT_MIME,
        headers={"Content-Disposition": f'attachment; filename="{REPORT_FILENAME}"'},
    )


@router.post("/repositories/bulk")
async def bulk_import_repositories(
    file: UploadFile, session: Session = Depends(get_session)
) -> dict:
    raw = await file.read()
    results = bulk_import.import_repositories_xlsx(session, raw)
    return {
        "rows": [r.as_dict() for r in results],
        "created": sum(1 for r in results if r.status == "created"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "errors": sum(1 for r in results if r.status == "error"),
    }
