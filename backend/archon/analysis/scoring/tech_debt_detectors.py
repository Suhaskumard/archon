"""Pure tech-debt detector functions (spec section 28).

Six detectors are pure lookups against data Phases 2-4 already computed - no re-parsing:
``long_functions``, ``large_classes``, ``circular_dependencies``, ``high_coupling``,
``dead_code_candidates`` (over persisted ``Component``/``Dependency`` rows) and
``global_state_from_assumptions`` (over Phase 4's ``assumptions`` table). The remaining
seven need one AST pass per source file, done by ``detect_ast_debt``: ``duplicate_logic``,
``low_cohesion``, ``deprecated_apis``, ``hardcoded_config``, ``broad_except``,
``silent_failure``, ``magic_numbers``.

Every function returns a list of finding dicts:
``{category, location, evidence, severity, impact, confidence, recommendation, component_id}``.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from archon.analysis.scoring.thresholds import (
    CATEGORY_DEFAULT_SEVERITY,
    DUPLICATE_LOGIC_MIN_NODES,
    HIGH_COUPLING_FAN_TOTAL,
    LARGE_CLASS_LOC,
    LARGE_CLASS_METHOD_COUNT,
    LONG_FUNCTION_LOC,
    LOW_COHESION_MIN_METHODS,
    MAGIC_NUMBER_ALLOWED,
)

TECH_DEBT_VERSION = "tech_debt.v1"

_IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", ".tox", "node_modules", "build", "dist",
    ".eggs", ".mypy_cache", ".pytest_cache", "site-packages",
}
_DEPRECATED_IMPORT_ROOTS = {"imp", "distutils", "optparse"}
_DEPRECATED_CALLS = {"asyncio.coroutine"}
_HARDCODED_NAME_RE = re.compile(r"(KEY|SECRET|PASSWORD|TOKEN)$")
_URL_RE = re.compile(r"^(https?://|[\w.-]+:\d{2,5}(/|$))")


def _finding(
    category: str,
    location: str,
    evidence: str,
    *,
    severity: str | None = None,
    impact: str | None = None,
    confidence: float = 1.0,
    recommendation: str | None = None,
    component_id: str | None = None,
) -> dict:
    return {
        "category": category,
        "location": location,
        "evidence": evidence,
        "severity": severity or CATEGORY_DEFAULT_SEVERITY[category],
        "impact": impact,
        "confidence": confidence,
        "recommendation": recommendation,
        "component_id": component_id,
    }


# --- detectors over already-persisted Component / Dependency rows -------------------


def long_functions(components: list) -> list[dict]:
    out = []
    for c in components:
        if c.kind.value not in ("FUNCTION", "METHOD"):
            continue
        loc = (c.metrics or {}).get("loc")
        if loc and loc > LONG_FUNCTION_LOC:
            out.append(_finding(
                "LONG_FUNCTION", f"{c.path}:{c.start_line or 0}",
                f"`{c.qualified_name}` is {loc} lines (> {LONG_FUNCTION_LOC})",
                impact="Harder to understand, test and safely change in one piece.",
                recommendation="Extract cohesive sub-steps into smaller functions.",
                component_id=c.id,
            ))
    return out


def large_classes(components: list, children_by_parent: dict[str, list]) -> list[dict]:
    out = []
    for c in components:
        if c.kind.value != "CLASS":
            continue
        loc = (c.metrics or {}).get("loc") or 0
        method_count = (c.metrics or {}).get("method_count")
        if method_count is None:
            method_count = sum(
                1 for k in children_by_parent.get(c.id, []) if k.kind.value == "METHOD"
            )
        if loc > LARGE_CLASS_LOC or method_count > LARGE_CLASS_METHOD_COUNT:
            out.append(_finding(
                "LARGE_CLASS", f"{c.path}:{c.start_line or 0}",
                f"`{c.qualified_name}` has {loc} lines and {method_count} methods",
                impact="A large class usually mixes multiple responsibilities.",
                recommendation="Split by responsibility (extract collaborator classes).",
                component_id=c.id,
            ))
    return out


def circular_dependencies(components: list) -> list[dict]:
    out = []
    for c in components:
        if c.kind.value != "MODULE":
            continue
        arch = (c.metrics or {}).get("architecture") or {}
        if arch.get("in_cycle"):
            out.append(_finding(
                "CIRCULAR_DEPENDENCY", c.path,
                f"`{c.qualified_name}` participates in an import cycle "
                f"(scc_size={arch.get('scc_size')})",
                impact="Import cycles make modules impossible to load/test in isolation.",
                recommendation="Break the cycle by extracting a shared module or inverting one import.",
                component_id=c.id,
            ))
    return out


def high_coupling(components: list) -> list[dict]:
    out = []
    for c in components:
        if c.kind.value != "MODULE":
            continue
        arch = (c.metrics or {}).get("architecture") or {}
        fan_in = arch.get("fan_in", 0) or 0
        fan_out = arch.get("fan_out", 0) or 0
        total = fan_in + fan_out
        if total > HIGH_COUPLING_FAN_TOTAL:
            out.append(_finding(
                "HIGH_COUPLING", c.path,
                f"`{c.qualified_name}` has fan_in={fan_in}, fan_out={fan_out} (total {total})",
                impact="Highly coupled modules are expensive and risky to change.",
                recommendation="Introduce a narrower interface or split responsibilities.",
                component_id=c.id,
            ))
    return out


def dead_code_candidates(components: list, dependencies: list) -> list[dict]:
    called_or_inherited = {
        d.dst_component_id
        for d in dependencies
        if d.dst_component_id and (d.kind.value if hasattr(d.kind, "value") else d.kind) in ("CALLS", "INHERITS")
    }
    out = []
    for c in components:
        if c.kind.value not in ("FUNCTION", "METHOD", "CLASS"):
            continue
        if c.is_entrypoint or c.is_test:
            continue
        if c.name.startswith("__") or c.name.startswith("test_"):
            continue
        if c.id in called_or_inherited:
            continue
        out.append(_finding(
            "DEAD_CODE_CANDIDATE", f"{c.path}:{c.start_line or 0}",
            f"`{c.qualified_name}` has no resolved caller/subclass in this snapshot",
            confidence=0.5,
            impact="May be unused, or called dynamically/externally (undetectable statically).",
            recommendation="Confirm it is unused, then delete it (or add the missing edge/entrypoint).",
            component_id=c.id,
        ))
    return out


def global_state_from_assumptions(assumptions: list) -> list[dict]:
    """Reuses Phase 4's ``global_state`` assumption heuristic - no new AST code."""
    conf_map = {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3}
    out = []
    for a in assumptions:
        if a.kind != "global_state":
            continue
        out.append(_finding(
            "GLOBAL_STATE", a.location or "",
            a.description,
            severity="HIGH" if a.risk == "HIGH" else CATEGORY_DEFAULT_SEVERITY["GLOBAL_STATE"],
            confidence=conf_map.get(a.confidence, 0.6),
            recommendation=a.suggested_test or "Encapsulate the global behind an accessor or inject it.",
            component_id=a.component_id,
        ))
    return out


# --- detectors needing a fresh AST pass ---------------------------------------------


def detect_ast_debt(repo_dir: Path, module_qn_for: Callable[[str], str]) -> list[dict]:
    """``module_qn_for(rel_posix_path) -> module qualified name`` (from the source extractor)."""
    out: list[dict] = []
    for path in sorted(Path(repo_dir).rglob("*.py")):
        rel_parts = path.relative_to(repo_dir).parts
        if any(p in _IGNORE_DIRS for p in rel_parts[:-1]):
            continue
        rel = path.relative_to(repo_dir).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        is_test_file = "tests" in rel_parts[:-1] or rel_parts[-1].startswith("test_")
        module_qn = module_qn_for(rel)
        out.extend(_scan_module(rel, module_qn, tree, skip_magic_numbers=is_test_file))
    return out


def _scan_module(
    rel: str, module_qn: str, tree: ast.Module, *, skip_magic_numbers: bool
) -> list[dict]:
    out: list[dict] = []
    out.extend(_deprecated_apis(rel, tree))
    out.extend(_hardcoded_config(rel, tree))
    out.extend(_broad_except_and_silent_failures(rel, tree))
    if not skip_magic_numbers:
        out.extend(_magic_numbers(rel, tree))
    out.extend(_duplicate_logic(rel, tree))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            out.extend(_low_cohesion(rel, node))
    return out


def _deprecated_apis(rel: str, tree: ast.Module) -> list[dict]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _DEPRECATED_IMPORT_ROOTS:
                    out.append(_finding(
                        "DEPRECATED_API", f"{rel}:{node.lineno}",
                        f"imports deprecated module `{alias.name}`",
                        recommendation=f"Replace `{alias.name}` with its modern equivalent.",
                    ))
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in _DEPRECATED_IMPORT_ROOTS:
                out.append(_finding(
                    "DEPRECATED_API", f"{rel}:{node.lineno}",
                    f"imports from deprecated module `{node.module}`",
                    recommendation=f"Replace `{node.module}` with its modern equivalent.",
                ))
        elif isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            if dotted in _DEPRECATED_CALLS:
                out.append(_finding(
                    "DEPRECATED_API", f"{rel}:{node.lineno}",
                    f"calls deprecated API `{dotted}`",
                    recommendation=f"Replace `{dotted}` with its modern equivalent.",
                ))
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "warn":
                args_text = " ".join(ast.unparse(a) for a in node.args)
                if "DeprecationWarning" in args_text:
                    out.append(_finding(
                        "DEPRECATED_API", f"{rel}:{node.lineno}",
                        f"raises DeprecationWarning: {ast.unparse(node)}",
                        confidence=0.8,
                        recommendation="Track and remove the deprecated path this warns about.",
                    ))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                dn = _dotted(deco) or (_dotted(deco.func) if isinstance(deco, ast.Call) else None)
                if dn and dn.split(".")[-1] == "deprecated":
                    out.append(_finding(
                        "DEPRECATED_API", f"{rel}:{node.lineno}",
                        f"`{node.name}` is decorated @{dn}",
                        recommendation=f"Migrate callers of `{node.name}` and remove it.",
                    ))
    return out


def _hardcoded_config(rel: str, tree: ast.Module) -> list[dict]:
    out = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        val = node.value
        if not isinstance(val, ast.Constant) or not isinstance(val.value, (str, int, float)):
            continue
        for tgt in node.targets:
            if not isinstance(tgt, ast.Name):
                continue
            name = tgt.id
            is_sensitive_name = name.isupper() and bool(_HARDCODED_NAME_RE.search(name))
            is_url_like = isinstance(val.value, str) and bool(_URL_RE.match(val.value))
            if is_sensitive_name or is_url_like:
                out.append(_finding(
                    "HARDCODED_CONFIG", f"{rel}:{node.lineno}",
                    f"`{name} = {ast.unparse(val)[:80]}` looks like hardcoded config/secret",
                    recommendation="Load from environment/config, never a literal in source.",
                ))
    return out


def _broad_except_and_silent_failures(rel: str, tree: ast.Module) -> list[dict]:
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        is_bare = node.type is None
        is_broad = is_bare or (
            isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException")
        )
        if is_broad:
            out.append(_finding(
                "BROAD_EXCEPT", f"{rel}:{node.lineno}",
                "bare `except:`" if is_bare else f"`except {ast.unparse(node.type)}:`",
                recommendation="Catch the specific exception(s) you expect to handle.",
            ))
        body = node.body
        is_silent = len(body) == 1 and (
            isinstance(body[0], ast.Pass)
            or (isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant))
        )
        if is_silent:
            out.append(_finding(
                "SILENT_FAILURE", f"{rel}:{node.lineno}",
                "except block swallows the error with no re-raise, log, or handling",
                recommendation="At minimum log the exception; re-raise unless truly optional.",
            ))
    return out


def _magic_numbers(rel: str, tree: ast.Module) -> list[dict]:
    named_constant_ids: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id.isupper() for t in node.targets
        ):
            named_constant_ids.add(id(node.value))

    def is_magic(n: ast.AST) -> bool:
        return (
            isinstance(n, ast.Constant)
            and isinstance(n.value, (int, float))
            and not isinstance(n.value, bool)
            and n.value not in MAGIC_NUMBER_ALLOWED
            and id(n) not in named_constant_ids
        )

    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            candidates = [node.left, *node.comparators]
        elif isinstance(node, ast.BinOp):
            candidates = [node.left, node.right]
        elif isinstance(node, ast.Call):
            candidates = list(node.args)
        else:
            continue
        for c in candidates:
            if is_magic(c):
                out.append(_finding(
                    "MAGIC_NUMBER", f"{rel}:{getattr(c, 'lineno', node.lineno)}",
                    f"unexplained literal `{c.value}` in `{ast.unparse(node)[:80]}`",
                    confidence=0.6,
                    recommendation="Extract to a named constant.",
                ))
    return out


class _Blank(ast.NodeTransformer):
    """Blanks names/constants so structurally-identical code hashes the same."""

    def visit_Name(self, node: ast.Name) -> ast.AST:
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.arg = "_"
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        return ast.copy_location(ast.Constant(value=None), node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.name = "_"
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.name = "_"
        self.generic_visit(node)
        return node


def _duplicate_logic(rel: str, tree: ast.Module) -> list[dict]:
    groups: dict[str, list[Any]] = defaultdict(list)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if sum(1 for _ in ast.walk(node)) < DUPLICATE_LOGIC_MIN_NODES:
            continue
        blanked = _Blank().visit(ast.parse(ast.unparse(node)))
        digest = ast.dump(blanked, annotate_fields=False)
        groups[digest].append(node)

    out = []
    for nodes in groups.values():
        if len(nodes) < 2:
            continue
        names = ", ".join(f"`{n.name}`" for n in nodes)
        for n in nodes:
            out.append(_finding(
                "DUPLICATE_LOGIC", f"{rel}:{n.lineno}",
                f"structurally identical to {names}",
                confidence=0.7,
                recommendation="Extract the shared logic into one function.",
            ))
    return out


def _low_cohesion(rel: str, cls: ast.ClassDef) -> list[dict]:
    methods = [
        n for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name != "__init__"
    ]
    if len(methods) < LOW_COHESION_MIN_METHODS:
        return []

    attrs_by_method: dict[str, set[str]] = {}
    for m in methods:
        attrs: set[str] = set()
        for node in ast.walk(m):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
            ):
                attrs.add(node.attr)
        attrs_by_method[m.name] = attrs

    names = [m.name for m in methods]
    parent = dict.fromkeys(names)
    for n in names:
        parent[n] = n

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        parent[find(x)] = find(y)

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if attrs_by_method[a] & attrs_by_method[b]:
                union(a, b)

    groups = {find(n) for n in names}
    if len(groups) > 1:
        return [_finding(
            "LOW_COHESION", f"{rel}:{cls.lineno}",
            f"`{cls.name}`'s methods split into {len(groups)} disjoint attribute-sharing groups",
            confidence=0.6,
            impact="The class likely bundles more than one responsibility.",
            recommendation="Split into separate classes along the disjoint method groups.",
        )]
    return []


def _dotted(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None
