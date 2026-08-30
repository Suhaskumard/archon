"""Phase 4 - software archaeology: behaviour reconstruction, "why does this exist?",
hidden-assumption detection (spec sections 24-26)."""

from archon.analysis.archaeology.assumptions import RawAssumption, detect_assumptions
from archon.analysis.archaeology.reconstruct import ARCHAEOLOGY_VERSION, run_archaeology

__all__ = [
    "detect_assumptions",
    "RawAssumption",
    "run_archaeology",
    "ARCHAEOLOGY_VERSION",
]
