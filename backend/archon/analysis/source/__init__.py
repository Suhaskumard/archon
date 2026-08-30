"""Phase 2 - Source intelligence (spec section 22).

Deterministic extraction of files, modules, classes, functions, methods, imports,
inheritance, calls, complexity and entry points from a Python checkout, using the
standard-library ``ast`` module.
"""

from archon.analysis.source.extractor import extract_repository
from archon.analysis.source.model import ExtractionResult, RawComponent, RawEdge

__all__ = ["extract_repository", "ExtractionResult", "RawComponent", "RawEdge"]
