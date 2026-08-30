"""Phase 3 - Architecture & dependency intelligence (spec section 23).

Turns the flat component/dependency model into a NetworkX graph, a module-level
``DEPENDS_ON`` view with derived ``TESTED_BY`` edges, and import-cycle detection.
"""

from archon.analysis.graph.builder import build_component_graph, build_module_graph
from archon.analysis.graph.derive import DeriveResult, derive_edges, find_cycles

__all__ = [
    "build_component_graph",
    "build_module_graph",
    "derive_edges",
    "find_cycles",
    "DeriveResult",
]
