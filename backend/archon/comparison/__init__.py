"""Repository comparison (spec section 45) - diff two completed analysis runs of the
same repository across architecture, dependencies, Legacy DNA, technical debt, risk,
coverage and change safety.

Comparison is an on-demand, cross-run operation (it needs two runs that already
exist), so it is exposed through the API/CLI rather than wired as a single-run
pipeline stage - the same shape as ``POST /runs/{id}/change-impact``.
"""

from __future__ import annotations

from archon.comparison.differ import COMPARISON_VERSION, compute_comparison
from archon.comparison.store import build_comparison, find_existing_comparison

__all__ = [
    "COMPARISON_VERSION",
    "build_comparison",
    "compute_comparison",
    "find_existing_comparison",
]
