"""Deterministic hidden-assumption detection (spec section 26).

Each heuristic is intentionally conservative - it should fire on a clear instance and stay
quiet on guarded code. Findings are (kind, description, path, line, function qn, evidence).
AI (mock) later assigns ``risk`` + ``suggested_test``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", ".tox", "node_modules", "build", "dist",
    ".eggs", ".mypy_cache", ".pytest_cache", "site-packages",
}
_MUTABLE_FACTORIES = {"dict", "list", "set", "defaultdict", "OrderedDict", "Counter"}
_DATE_NOW = {"now", "utcnow", "today"}
_IO_ROOTS = {"requests", "httpx", "urllib", "urllib3", "socket", "boto3", "psycopg", "redis"}


@dataclass
class RawAssumption:
    kind: str
    description: str
    path: str
    line: int
    function_qn: str
    evidence: str


def detect_assumptions(repo_dir: Path, module_qn_for) -> list[RawAssumption]:
    """``module_qn_for(rel_posix_path) -> module qualified name`` (from the source extractor)."""
    out: list[RawAssumption] = []
    for path in sorted(Path(repo_dir).rglob("*.py")):
        rel_parts = path.relative_to(repo_dir).parts
        if any(p in _IGNORE_DIRS for p in rel_parts[:-1]):
            continue
        rel = path.relative_to(repo_dir).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        module_qn = module_qn_for(rel)
        _ModuleScan(rel, module_qn, tree, out).run()
    return out


class _ModuleScan:
    def __init__(self, rel: str, module_qn: str, tree: ast.Module, sink: list[RawAssumption]):
        self.rel = rel
        self.module_qn = module_qn
        self.tree = tree
        self.sink = sink
        self.module_globals = self._module_globals(tree)
        self.import_roots = self._import_roots(tree)

    @staticmethod
    def _module_globals(tree: ast.Module) -> dict[str, str]:
        """name -> factory kind for module-level mutable assignments."""
        found: dict[str, str] = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            val = node.value
            factory = None
            if isinstance(val, (ast.Dict, ast.List, ast.Set)):
                factory = {ast.Dict: "dict", ast.List: "list", ast.Set: "set"}[type(val)]
            elif isinstance(val, ast.Call) and isinstance(val.func, ast.Name) and val.func.id in _MUTABLE_FACTORIES:
                factory = val.func.id
            if factory:
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        found[tgt.id] = factory
        return found

    @staticmethod
    def _import_roots(tree: ast.Module) -> set[str]:
        roots: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        return roots

    def run(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._scan_function(node)

    # --- per-function -----------------------------------------------------

    def _scan_function(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qn = f"{self.module_qn}.{fn.name}"
        params = {a.arg for a in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs)}
        params.discard("self")
        params.discard("cls")
        guarded_none = self._names_guarded_against_none(fn)
        guarded_membership = self._membership_checks(fn)
        length_checked = self._length_checks(fn)
        zero_checked = self._zero_checks(fn)

        for sub in ast.walk(fn):
            self._check_division(sub, params, zero_checked, qn)
            self._check_global_state(sub, fn, qn)
            self._check_dict_key(sub, guarded_membership, qn)
            self._check_env(sub, qn)
            self._check_timezone(sub, qn)
            self._check_empty_collection(sub, params, length_checked, qn)
            self._check_null_deref(sub, fn, params, guarded_none, qn)

    def _emit(self, kind: str, desc: str, line: int, qn: str, evidence: str) -> None:
        self.sink.append(
            RawAssumption(kind=kind, description=desc, path=self.rel, line=line,
                          function_qn=qn, evidence=evidence)
        )

    # --- individual heuristics -----------------------------------------

    def _check_division(
        self, node: ast.AST, params: set[str], zero_checked: set[str], qn: str
    ) -> None:
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            rhs = node.right
            if isinstance(rhs, ast.Name) and rhs.id in params and rhs.id not in zero_checked:
                self._emit(
                    "division",
                    f"divides by parameter `{rhs.id}` with no zero check",
                    node.lineno, qn, ast.unparse(node),
                )

    def _check_global_state(self, node: ast.AST, fn: ast.AST, qn: str) -> None:
        if isinstance(node, ast.Name) and node.id in self.module_globals and isinstance(
            node.ctx, (ast.Load, ast.Store)
        ):
            # only report once per (global, function) and only for real use
            key = (node.id, qn, "global_state")
            if key in getattr(self, "_seen_global", set()):
                return
            self._seen_global = getattr(self, "_seen_global", set()) | {key}
            self._emit(
                "global_state",
                f"reads/mutates module-global `{node.id}` "
                f"({self.module_globals[node.id]}) - shared mutable state",
                node.lineno, qn, node.id,
            )

    def _check_dict_key(self, node: ast.AST, guarded: set[str], qn: str) -> None:
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Subscript):
            base = node.target.value
            if isinstance(base, ast.Name) and base.id not in guarded:
                self._emit(
                    "dict_key",
                    f"`{ast.unparse(node.target)}` assumes the key already exists in `{base.id}`",
                    node.lineno, qn, ast.unparse(node),
                )

    def _check_env(self, node: ast.AST, qn: str) -> None:
        # os.environ[X]
        if isinstance(node, ast.Subscript) and _dotted(node.value) == "os.environ":
            self._emit("environment", "reads os.environ[...] with no default",
                       node.lineno, qn, ast.unparse(node))
        # os.getenv(X) / os.environ.get(X) with one arg
        if isinstance(node, ast.Call):
            callee = _dotted(node.func)
            if callee in ("os.getenv", "os.environ.get") and len(node.args) == 1 and not node.keywords:
                self._emit("environment", f"`{callee}` used without a default value",
                           node.lineno, qn, ast.unparse(node))

    def _check_timezone(self, node: ast.AST, qn: str) -> None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _DATE_NOW and not node.args and not any(
                k.arg in ("tz", "tzinfo") for k in node.keywords
            ):
                base = _dotted(node.func.value) or ""
                if base.endswith("datetime") or base.endswith("date") or base == "datetime":
                    self._emit("timezone", f"`{ast.unparse(node)}` returns a naive local datetime",
                               node.lineno, qn, ast.unparse(node))

    def _check_empty_collection(
        self, node: ast.AST, params: set[str], length_checked: set[str], qn: str
    ) -> None:
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            name = node.value.id
            idx = node.slice
            if (
                name in params
                and name not in length_checked
                and isinstance(idx, ast.Constant)
                and idx.value == 0
            ):
                self._emit("empty_collection", f"`{name}[0]` assumes `{name}` is non-empty",
                           node.lineno, qn, ast.unparse(node))
        if isinstance(node, ast.Call):
            callee = _dotted(node.func)
            if callee in ("min", "max") and node.args and isinstance(node.args[0], ast.Name):
                nm = node.args[0].id
                if nm in params and nm not in length_checked:
                    self._emit("empty_collection", f"`{callee}({nm})` assumes `{nm}` is non-empty",
                               node.lineno, qn, ast.unparse(node))

    def _check_null_deref(
        self, node: ast.AST, fn: ast.AST, params: set[str], guarded_none: set[str], qn: str
    ) -> None:
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            nm = node.value.id
            if nm in params and nm not in guarded_none:
                key = (nm, qn, "null")
                seen = getattr(self, "_seen_null", set())
                if key in seen:
                    return
                self._seen_null = seen | {key}
                self._emit(
                    "null",
                    f"dereferences parameter `{nm}` (`{ast.unparse(node)}`) without a None check",
                    node.lineno, qn, ast.unparse(node),
                )

    # --- guard collectors --------------------------------------------

    @staticmethod
    def _names_guarded_against_none(fn: ast.AST) -> set[str]:
        guarded: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Compare) and any(
                isinstance(op, (ast.Is, ast.IsNot, ast.Eq, ast.NotEq)) for op in node.ops
            ):
                operands = [node.left, *node.comparators]
                has_none = any(isinstance(o, ast.Constant) and o.value is None for o in operands)
                if has_none:
                    for o in operands:
                        if isinstance(o, ast.Name):
                            guarded.add(o.id)
            if isinstance(node, ast.BoolOp):
                for v in node.values:
                    if isinstance(v, ast.Name):
                        guarded.add(v.id)
            if isinstance(node, (ast.If, ast.While)) and isinstance(node.test, ast.Name):
                guarded.add(node.test.id)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) and isinstance(node.operand, ast.Name):
                guarded.add(node.operand.id)
        return guarded

    @staticmethod
    def _membership_checks(fn: ast.AST) -> set[str]:
        """dict names that get an `in` / `not in` check or `.setdefault` / try somewhere."""
        names: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Compare):
                for op, comp in zip(node.ops, node.comparators, strict=False):
                    if isinstance(op, (ast.In, ast.NotIn)) and isinstance(comp, ast.Name):
                        names.add(comp.id)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "setdefault" and isinstance(node.func.value, ast.Name):
                    names.add(node.func.value.id)
            if isinstance(node, ast.Try):
                for h in node.handlers:
                    ht = h.type
                    if ht and "KeyError" in (ast.unparse(ht) if ht else ""):
                        for sub in ast.walk(node):
                            if isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name):
                                names.add(sub.value.id)
        return names

    @staticmethod
    def _zero_checks(fn: ast.AST) -> set[str]:
        """param names compared against 0, or used in a truthiness guard (0 is falsy)."""
        names: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                touches_zero = any(
                    isinstance(o, ast.Constant) and o.value == 0 for o in operands
                )
                if touches_zero:
                    for o in operands:
                        if isinstance(o, ast.Name):
                            names.add(o.id)
            if isinstance(node, (ast.If, ast.While)) and isinstance(node.test, ast.Name):
                names.add(node.test.id)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) and isinstance(
                node.operand, ast.Name
            ):
                names.add(node.operand.id)
            if isinstance(node, ast.BoolOp):
                for v in node.values:
                    if isinstance(v, ast.Name):
                        names.add(v.id)
        return names

    @staticmethod
    def _length_checks(fn: ast.AST) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and _dotted(node.func) == "len" and node.args:
                if isinstance(node.args[0], ast.Name):
                    names.add(node.args[0].id)
            if isinstance(node, (ast.If, ast.While)) and isinstance(node.test, ast.Name):
                names.add(node.test.id)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) and isinstance(node.operand, ast.Name):
                names.add(node.operand.id)
        return names


def _dotted(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None
