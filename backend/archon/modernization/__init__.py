"""Modernization (spec section 46) - the ``MODERNIZING`` stage.

Turns the run's deterministic findings (Legacy DNA, technical debt, hotspots, change
safety, import cycles) into an ordered, evidence-backed modernization plan: a mock AI
op picks the strategy/risk/effort/impact/rationale per target, and a deterministic
versioned engine assigns ``order_index`` from the dependency + change-safety graph.
"""

from __future__ import annotations

from archon.modernization.planner import (
    MODERNIZATION_VERSION,
    ModernizationSummary,
    assemble_targets,
    compute_safe_order,
    generate_modernization_plan,
)

__all__ = [
    "MODERNIZATION_VERSION",
    "ModernizationSummary",
    "assemble_targets",
    "compute_safe_order",
    "generate_modernization_plan",
]
