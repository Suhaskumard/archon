"""Coverage analysis (spec sections 33-35) - parses the ``coverage.xml`` (Cobertura
format, produced by ``coverage.py``'s ``xml`` report) that ``execution/runner.py``
already captures as a raw artifact, and maps it onto ``Component`` line ranges.

Not wired back into ``LegacyDNA.coverage``/``ChangeAssessment.coverage`` - those stay
the documented proxy they already are (see ``testing/gaps.py`` module docstring for the
scope-cut rationale). This module's output feeds ``TestGap.coverage_pct`` directly.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from archon.db.models import Component

COVERAGE_VERSION = "coverage_analysis.v1"


@dataclass
class FileCoverage:
    executable_lines: set[int] = field(default_factory=set)
    covered_lines: set[int] = field(default_factory=set)


def parse_coverage_xml(xml_text: str) -> dict[str, FileCoverage]:
    """Parse a Cobertura-format ``coverage.xml``. Returns ``{filename: FileCoverage}``.

    Malformed/empty input yields an empty map rather than raising - coverage data is
    best-effort enrichment, never a hard requirement for the pipeline to complete.
    """
    if not xml_text.strip():
        return {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    by_file: dict[str, FileCoverage] = {}
    for cls in root.iter("class"):
        filename = cls.get("filename")
        if not filename:
            continue
        fc = by_file.setdefault(filename, FileCoverage())
        lines_el = cls.find("lines")
        if lines_el is None:
            continue
        for line in lines_el.findall("line"):
            try:
                number = int(line.get("number", ""))
                hits = int(line.get("hits", "0"))
            except ValueError:
                continue
            fc.executable_lines.add(number)
            if hits > 0:
                fc.covered_lines.add(number)
    return by_file


def component_coverage_pct(component: Component, file_coverage: dict[str, FileCoverage]) -> float:
    """Fraction (0.0-1.0) of ``component``'s executable lines that were hit.

    0.0 when the file is absent from the coverage report or the component has no
    line range - both read as "not exercised", the honest default for a gap analysis.
    """
    fc = file_coverage.get(component.path)
    if fc is None or component.start_line is None or component.end_line is None:
        return 0.0
    lo, hi = component.start_line, component.end_line
    in_range = {n for n in fc.executable_lines if lo <= n <= hi}
    if not in_range:
        return 0.0
    covered = in_range & fc.covered_lines
    return len(covered) / len(in_range)
