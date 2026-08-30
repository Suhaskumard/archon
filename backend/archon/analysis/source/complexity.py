"""Cyclomatic complexity from a Python AST (spec section 22).

Model (documented, deterministic, versioned as ``complexity.v1``):

    complexity = 1
      + 1 for each   if / elif        (ast.If)
      + 1 for each   for / async for  (ast.For, ast.AsyncFor)
      + 1 for each   while            (ast.While)
      + 1 for each   except handler   (ast.ExceptHandler)
      + 1 for each   with item        (ast.withitem)         # each context manager
      + 1 for each   boolean operator beyond the first in a BoolOp
      + 1 for each   comprehension    (each 'for') and each comprehension 'if'
      + 1 for each   ternary          (ast.IfExp)
      + 1 for each   match case       (ast.match_case)
      + 1 for each   assert           (ast.Assert)

``else``/``finally`` add no decision point (they are the fall-through). Nested function
and class definitions are **not** counted toward the enclosing scope - each callable is
measured on its own body.
"""

from __future__ import annotations

import ast

COMPLEXITY_VERSION = "complexity.v1"

_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


class _Counter(ast.NodeVisitor):
    def __init__(self) -> None:
        self.score = 1

    # do not descend into nested callables/classes
    def _skip_nested(self, node: ast.AST) -> None:
        return None

    visit_FunctionDef = _skip_nested
    visit_AsyncFunctionDef = _skip_nested
    visit_ClassDef = _skip_nested
    visit_Lambda = _skip_nested

    def visit_If(self, node: ast.If) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self.score += len(node.items)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.score += len(node.items)
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.score += len(node.values) - 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_match_case(self, node: ast.match_case) -> None:
        self.score += 1
        self.generic_visit(node)

    def _comprehension(self, node: ast.AST) -> None:
        for gen in node.generators:  # type: ignore[attr-defined]
            self.score += 1 + len(gen.ifs)
        self.generic_visit(node)

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension


def complexity_of_body(body: list[ast.stmt]) -> int:
    counter = _Counter()
    for stmt in body:
        counter.visit(stmt)
    return counter.score


def complexity_of_node(node: ast.AST) -> int:
    """Complexity of a single def/async-def (measures its body only)."""
    body = getattr(node, "body", [])
    return complexity_of_body(body)
