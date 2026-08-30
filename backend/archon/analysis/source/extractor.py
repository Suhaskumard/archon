"""Python source extractor (spec section 22).

``extract_repository`` walks a checkout and returns an :class:`ExtractionResult` of
backend-independent components + edges. Two passes:

1. discover every ``.py`` file, build the module-name index and config-file list;
2. parse each module with ``ast``, emit components + raw import/inherit/call records,
   then resolve those records into edges against the global index (see ``resolve.py``).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from archon.analysis.source.classify import (
    is_config_path,
    is_test_path,
    module_imports_test_framework,
)
from archon.analysis.source.complexity import COMPLEXITY_VERSION, complexity_of_body
from archon.analysis.source.entrypoints import declared_console_scripts
from archon.analysis.source.model import ExtractionResult, RawComponent
from archon.analysis.source.resolve import ModuleScope, resolve_edges
from archon.config import RepositoryLimits, get_settings
from archon.core.logging import get_logger
from archon.domain.enums import ComponentKind, DependencyKind

log = get_logger("archon.analysis.source")

_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", ".tox", ".nox",
    "node_modules", "build", "dist", ".eggs", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "site-packages", ".idea", ".vscode",
}
_MAX_NEST_DEPTH = 3
_MAX_CALLS_PER_MODULE = 500


# --- raw, pre-resolution records -----------------------------------------------------


@dataclass
class _ImportRec:
    target_module: str          # absolute dotted module (relative already resolved)
    imported_names: list[tuple[str, str]]  # (original, alias)
    line: int
    is_star: bool = False


@dataclass
class _InheritRec:
    class_key: str
    base_dotted: str
    line: int


@dataclass
class _CallRec:
    src_key: str
    callee_dotted: str
    base_name: str
    via_self: bool
    line: int


@dataclass
class _ModuleParse:
    module_qn: str
    module_key: str
    path: str
    is_package: bool
    imports: list[_ImportRec] = field(default_factory=list)
    inherits: list[_InheritRec] = field(default_factory=list)
    calls: list[_CallRec] = field(default_factory=list)
    alias_map: dict[str, str] = field(default_factory=dict)   # local name -> dotted target
    module_defs: set[str] = field(default_factory=set)        # top-level class/func names
    class_of_component: dict[str, str] = field(default_factory=dict)  # comp key -> class qn


# --- helpers -----------------------------------------------------------------------


def _module_qn_for(rel_posix: str) -> tuple[str, bool]:
    parts = [p for p in rel_posix.split("/") if p]
    if parts and parts[0] == "src":
        parts = parts[1:]
    is_package = parts[-1] == "__init__.py"
    if is_package:
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]  # strip .py
    return ".".join(parts) if parts else "(root)", is_package


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _decorator_names(node: ast.AST) -> list[str]:
    out: list[str] = []
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = _dotted(target)
        if name:
            out.append(name)
    return out


def _raised_exceptions(body: list[ast.stmt]) -> list[str]:
    found: list[str] = []
    for stmt in body:
        for sub in ast.walk(stmt):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and sub is not stmt:
                continue
            if isinstance(sub, ast.Raise) and sub.exc is not None:
                exc = sub.exc.func if isinstance(sub.exc, ast.Call) else sub.exc
                name = _dotted(exc) if isinstance(exc, (ast.Name, ast.Attribute)) else None
                if name:
                    found.append(name.split(".")[-1])
    return sorted(set(found))


def _has_yield(body: list[ast.stmt]) -> bool:
    for stmt in body:
        for sub in ast.walk(stmt):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub is not stmt:
                continue
            if isinstance(sub, (ast.Yield, ast.YieldFrom)):
                return True
    return False


_SCOPE_BOUNDARY = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _iter_calls_in_scope(node: ast.AST):
    """Yield ast.Call nodes reachable from ``node`` without crossing a def/class/lambda."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Call):
            yield child
            yield from _iter_calls_in_scope(child)
        elif isinstance(child, _SCOPE_BOUNDARY):
            continue
        else:
            yield from _iter_calls_in_scope(child)


def _sloc(source_lines: list[str], start: int, end: int) -> int:
    n = 0
    for i in range(start - 1, min(end, len(source_lines))):
        s = source_lines[i].strip()
        if s and not s.startswith("#"):
            n += 1
    return n


# --- per-module extraction --------------------------------------------------------


class _ModuleExtractor:
    def __init__(self, mp: _ModuleParse, tree: ast.Module, source_lines: list[str]) -> None:
        self.mp = mp
        self.tree = tree
        self.lines = source_lines
        self.components: list[RawComponent] = []
        self.entrypoints: list[dict] = []

    def run(self) -> None:
        self._collect_imports(self.tree.body)
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(node, parent_key=self.mp.module_key, qn_prefix=self.mp.module_qn, depth=0)
                self.mp.module_defs.add(node.name)
            elif isinstance(node, ast.ClassDef):
                self._class(node, parent_key=self.mp.module_key, qn_prefix=self.mp.module_qn)
                self.mp.module_defs.add(node.name)
        # module-level calls + framework/main signals
        self._collect_calls(self.tree.body, src_key=self.mp.module_key, via_self=False)
        self._module_signals()

    # imports ---------------------------------------------------------------

    def _collect_imports(self, body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # `import a.b` / `import a.b as c` -> depend on module `a.b`
                    self.mp.imports.append(_ImportRec(alias.name, [], node.lineno))
                    if alias.asname:
                        self.mp.alias_map[alias.asname] = alias.name
                    else:
                        # binds the top name; treat `a` as an alias for `a`
                        top = alias.name.split(".")[0]
                        self.mp.alias_map[top] = top
            elif isinstance(node, ast.ImportFrom):
                target = self._resolve_relative(node.module, node.level)
                star = any(a.name == "*" for a in node.names)
                names = [(a.name, a.asname or a.name) for a in node.names if a.name != "*"]
                self.mp.imports.append(_ImportRec(target, names, node.lineno, is_star=star))
                for orig, bound in names:
                    self.mp.alias_map[bound] = f"{target}.{orig}" if target else orig

    def _resolve_relative(self, module: str | None, level: int) -> str:
        if not level:
            return module or ""
        pkg_parts = self.mp.module_qn.split(".")
        if not self.mp.is_package:
            pkg_parts = pkg_parts[:-1]
        base = pkg_parts[: len(pkg_parts) - (level - 1)] if level > 1 else pkg_parts
        abs_parts = list(base)
        if module:
            abs_parts += module.split(".")
        return ".".join(p for p in abs_parts if p)

    # functions / methods -------------------------------------------------

    def _function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, parent_key: str, qn_prefix: str, depth: int
    ) -> None:
        qn = f"{qn_prefix}.{node.name}"
        is_method = parent_key.startswith("cls:")
        kind = ComponentKind.METHOD if is_method else ComponentKind.FUNCTION
        key = f"{'meth' if is_method else 'fn'}:{qn}"
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        args = [a.arg for a in node.args.args] + [a.arg for a in node.args.posonlyargs]
        if node.args.vararg:
            args.append("*" + node.args.vararg.arg)
        if node.args.kwarg:
            args.append("**" + node.args.kwarg.arg)
        metrics = {
            "complexity": complexity_of_body(node.body),
            "complexity_model": COMPLEXITY_VERSION,
            "loc": end - node.lineno + 1,
            "sloc": _sloc(self.lines, node.lineno, end),
            "param_count": len(args),
            "args": args,
            "decorators": _decorator_names(node),
            "returns_annotation": _dotted(node.returns) if node.returns is not None else None,
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "is_generator": _has_yield(node.body),
            "raises": _raised_exceptions(node.body),
            "has_docstring": ast.get_docstring(node) is not None,
        }
        self.components.append(
            RawComponent(
                key=key, kind=kind, name=node.name, qualified_name=qn, path=self.mp.path,
                start_line=node.lineno, end_line=end, parent_key=parent_key, metrics=metrics,
                attributes={"is_method": is_method},
            )
        )
        if is_method:
            self.mp.class_of_component[key] = qn_prefix
        self._collect_calls(node.body, src_key=key, via_self=is_method)
        if depth < _MAX_NEST_DEPTH:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._function(child, parent_key=key, qn_prefix=qn, depth=depth + 1)

    def _class(self, node: ast.ClassDef, *, parent_key: str, qn_prefix: str) -> None:
        qn = f"{qn_prefix}.{node.name}"
        key = f"cls:{qn}"
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        methods = [c.name for c in node.body if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self.components.append(
            RawComponent(
                key=key, kind=ComponentKind.CLASS, name=node.name, qualified_name=qn,
                path=self.mp.path, start_line=node.lineno, end_line=end, parent_key=parent_key,
                metrics={
                    "loc": end - node.lineno + 1,
                    "sloc": _sloc(self.lines, node.lineno, end),
                    "method_count": len(methods),
                    "decorators": _decorator_names(node),
                    "has_docstring": ast.get_docstring(node) is not None,
                },
                attributes={"bases": [_dotted(b) for b in node.bases if _dotted(b)]},
            )
        )
        for base in node.bases:
            b = _dotted(base)
            if b:
                self.mp.inherits.append(_InheritRec(class_key=key, base_dotted=b, line=node.lineno))
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(child, parent_key=key, qn_prefix=qn, depth=0)
            elif isinstance(child, ast.ClassDef):
                self._class(child, parent_key=key, qn_prefix=qn)

    # calls ---------------------------------------------------------------

    def _collect_calls(self, body: list[ast.stmt], *, src_key: str, via_self: bool) -> None:
        """Record every call in ``body`` that is NOT inside a nested def/class scope."""
        for stmt in body:
            if isinstance(stmt, _SCOPE_BOUNDARY):
                continue  # nested def/class - its calls are attributed to its own component
            for call in _iter_calls_in_scope(stmt):
                self._record_call(call, src_key)

    def _record_call(self, call: ast.Call, src_key: str) -> None:
        if len(self.mp.calls) >= _MAX_CALLS_PER_MODULE:
            return
        dotted = _dotted(call.func)
        if not dotted:
            return
        parts = dotted.split(".")
        base = parts[0]
        via_self = base == "self" and len(parts) == 2
        self.mp.calls.append(
            _CallRec(src_key=src_key, callee_dotted=dotted, base_name=base, via_self=via_self,
                     line=getattr(call, "lineno", 0))
        )

    # module-level signals ---------------------------------------------

    def _module_signals(self) -> None:
        for node in self.tree.body:
            if (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"
            ):
                self.entrypoints.append(
                    {"kind": "main_guard", "path": self.mp.path,
                     "detail": '__name__ == "__main__"', "component_key": self.mp.module_key}
                )
        src = "\n".join(self.lines)
        for needle, kind in (
            ("uvicorn.run", "asgi_server"),
            ("FastAPI(", "fastapi_app"),
            ("Flask(", "flask_app"),
        ):
            if needle in src:
                self.entrypoints.append(
                    {"kind": kind, "path": self.mp.path, "detail": needle,
                     "component_key": self.mp.module_key}
                )


# --- top-level driver -----------------------------------------------------------


def _iter_files(repo_dir: Path):
    for path in sorted(repo_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(repo_dir).parts
        if any(part in _IGNORE_DIRS for part in rel_parts[:-1]):
            continue
        yield path


def extract_repository(
    repo_dir: Path, limits: RepositoryLimits | None = None
) -> ExtractionResult:
    limits = limits or get_settings().limits
    result = ExtractionResult()

    py_files: list[Path] = []
    for path in _iter_files(repo_dir):
        rel = path.relative_to(repo_dir).as_posix()
        if path.suffix == ".py":
            py_files.append(path)
        elif is_config_path(rel):
            result.components.append(
                RawComponent(
                    key=f"file:{rel}", kind=ComponentKind.FILE, name=path.name,
                    qualified_name=rel, path=rel, start_line=None, end_line=None,
                    parent_key=None,
                    metrics={"size_bytes": path.stat().st_size},
                    attributes={"is_config": True},
                )
            )
            result.file_count += 1

    if len(py_files) > limits.max_file_count:
        result.degraded = True
        result.degraded_reason = (
            f"{len(py_files)} Python files exceeds max_file_count={limits.max_file_count}; "
            f"analysed the first {limits.max_file_count} by path order"
        )
        py_files = py_files[: limits.max_file_count]

    # pass 1: module index
    module_index: dict[str, str] = {}   # module_qn -> module component key
    parses: list[tuple[Path, str, _ModuleParse]] = []
    for path in py_files:
        rel = path.relative_to(repo_dir).as_posix()
        qn, is_pkg = _module_qn_for(rel)
        mkey = f"mod:{qn}"
        module_index[qn] = mkey
        parses.append((path, rel, _ModuleParse(qn, mkey, rel, is_pkg)))

    # pass 2: parse + extract
    scopes: list[ModuleScope] = []
    for path, rel, mp in parses:
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            result.skipped.append({"path": rel, "reason": f"unreadable: {exc}"})
            continue
        size = len(raw.encode("utf-8", "ignore"))
        over_size = size > limits.max_file_size_bytes

        # FILE + MODULE components
        result.components.append(
            RawComponent(
                key=f"file:{rel}", kind=ComponentKind.FILE, name=path.name,
                qualified_name=rel, path=rel, start_line=None, end_line=None, parent_key=None,
                metrics={"size_bytes": size}, attributes={"language": "python"},
            )
        )
        result.file_count += 1
        module_attrs = {
            "is_package": mp.is_package,
            "is_test": is_test_path(rel),
        }
        module_metrics: dict = {"size_bytes": size}

        if over_size:
            result.skipped.append(
                {"path": rel, "reason": f"file {size}B exceeds max_file_size_bytes"}
            )
            module_attrs["skipped"] = "oversize"
            result.components.append(
                RawComponent(
                    key=mp.module_key, kind=ComponentKind.MODULE, name=qn_last(mp.module_qn),
                    qualified_name=mp.module_qn, path=rel, start_line=1, end_line=None,
                    parent_key=f"file:{rel}", metrics=module_metrics, attributes=module_attrs,
                )
            )
            result.module_count += 1
            continue

        try:
            tree = ast.parse(raw, filename=rel)
        except SyntaxError as exc:
            result.parse_errors.append(
                {"path": rel, "message": exc.msg or "syntax error", "line": exc.lineno}
            )
            module_attrs["parse_error"] = exc.msg
            result.components.append(
                RawComponent(
                    key=mp.module_key, kind=ComponentKind.MODULE, name=qn_last(mp.module_qn),
                    qualified_name=mp.module_qn, path=rel, start_line=1, end_line=None,
                    parent_key=f"file:{rel}", metrics=module_metrics, attributes=module_attrs,
                )
            )
            result.module_count += 1
            continue

        lines = raw.splitlines()
        module_metrics.update(
            {
                "loc": len(lines),
                "sloc": _sloc(lines, 1, len(lines)),
                "complexity": complexity_of_body(tree.body),
                "complexity_model": COMPLEXITY_VERSION,
                "has_docstring": ast.get_docstring(tree) is not None,
            }
        )
        me = _ModuleExtractor(mp, tree, lines)
        me.run()

        module_attrs["imports_test_framework"] = module_imports_test_framework(
            {rec.target_module.split(".")[0] for rec in mp.imports if rec.target_module}
        )
        result.components.append(
            RawComponent(
                key=mp.module_key, kind=ComponentKind.MODULE, name=qn_last(mp.module_qn),
                qualified_name=mp.module_qn, path=rel, start_line=1, end_line=len(lines),
                parent_key=f"file:{rel}", metrics=module_metrics, attributes=module_attrs,
            )
        )
        result.module_count += 1
        result.components.extend(me.components)
        result.entrypoints.extend(me.entrypoints)
        scopes.append(
            ModuleScope(
                module_qn=mp.module_qn,
                module_key=mp.module_key,
                alias_map=mp.alias_map,
                module_defs=mp.module_defs,
                class_of_component=mp.class_of_component,
                imports=[(r.target_module, r.imported_names, r.line, r.is_star) for r in mp.imports],
                inherits=[(r.class_key, r.base_dotted, r.line) for r in mp.inherits],
                calls=[(r.src_key, r.callee_dotted, r.base_name, r.via_self, r.line) for r in mp.calls],
            )
        )

    # declared console scripts -> entrypoints on their target functions/modules
    for script in declared_console_scripts(repo_dir):
        target_mod = script["module"]
        comp_key = None
        if script["function"] and f"{target_mod}.{script['function']}" in {
            c.qualified_name for c in result.components if c.kind == ComponentKind.FUNCTION
        }:
            comp_key = f"fn:{target_mod}.{script['function']}"
        elif target_mod in module_index:
            comp_key = module_index[target_mod]
        result.entrypoints.append(
            {"kind": "console_script", "path": script["source"],
             "detail": f"{script['name']} = {target_mod}:{script['function']}",
             "component_key": comp_key}
        )

    # resolve import/inherit/call records into edges
    index_by_qn: dict[tuple[str, str], str] = {}
    for c in result.components:
        index_by_qn[(c.kind.value, c.qualified_name)] = c.key
    result.edges.extend(resolve_edges(scopes, index_by_qn, module_index))

    # mark entrypoint components
    ep_keys = {ep["component_key"] for ep in result.entrypoints if ep.get("component_key")}
    for c in result.components:
        if c.key in ep_keys:
            c.attributes["is_entrypoint"] = True

    log.info(
        "source extraction complete",
        extra={"extra_fields": {"modules": result.module_count, **result.counts()}},
    )
    return result


def qn_last(qn: str) -> str:
    return qn.rsplit(".", 1)[-1] if qn else "(root)"


# CONTAINS edges are derived from parent_key at persist time, so the extractor does not
# emit them explicitly (keeps the edge list to IMPORTS / CALLS / INHERITS).
_ = DependencyKind  # referenced for documentation / import stability
