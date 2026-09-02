"""Reporting (spec sections 49-50): the Excel workbook + ``repositories.xlsx`` bulk input.

``queries`` is a thin read layer over the existing API router functions - the report and
the JSON API share one data path, no separate engine (spec 49). ``workbook`` renders the
14-sheet ``ARCHON_Legacy_Analysis.xlsx``; ``bulk_import`` validates a ``repositories.xlsx``
and enqueues ordinary ``AnalysisRun``s through ``JobManager``.
"""

from __future__ import annotations

from archon.reporting.bulk_import import BulkRowResult, import_repositories_xlsx
from archon.reporting.workbook import REPORT_MIME, build_report, report_bytes

__all__ = [
    "REPORT_MIME",
    "BulkRowResult",
    "build_report",
    "import_repositories_xlsx",
    "report_bytes",
]
