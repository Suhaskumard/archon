"""Cross-module resolution of import / inherit / call records into edges (spec section 22).

Resolution is *best-effort and conservative*: an edge is only marked ``resolved`` when its
target is an actual component in this snapshot. Unresolved references to something the
module explicitly imported are still emitted (``external=True``, ``dst_key=None``) because
they describe a real outbound dependency; unresolved bare names (locals, builtins,
duck-typed attribute calls) are dropped to keep the graph high-signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from archon.analysis.source.model import RawEdge
from archon.domain.enums import DependencyKind


@dataclass
class ModuleScope:
    module_qn: str
    module_key: str
    alias_map: dict[str, str]
    module_defs: set[str]
    class_of_component: dict[str, str]
    imports: list[tuple[str, list[tuple[str, str]], int, bool]]
    inherits: list[tuple[str, str, int]]
    calls: list[tuple[str, str, str, bool, int]]
    _seen: set[tuple] = field(default_factory=set)


class _Index:
    def __init__(self, by_qn: dict[tuple[str, str], str], modules: dict[str, str]) -> None:
        self._by_qn = by_qn
        self._modules = modules

    def module(self, qn: str) -> str | None:
        return self._modules.get(qn)

    def klass(self, qn: str) -> str | None:
        return self._by_qn.get(("CLASS", qn))

    def method(self, qn: str) -> str | None:
        return self._by_qn.get(("METHOD", qn))

    def symbol(self, qn: str) -> str | None:
        return (
            self._by_qn.get(("FUNCTION", qn))
            or self._by_qn.get(("CLASS", qn))
            or self._by_qn.get(("METHOD", qn))
        )


def resolve_edges(
    scopes: list[ModuleScope],
    index_by_qn: dict[tuple[str, str], str],
    module_index: dict[str, str],
) -> list[RawEdge]:
    idx = _Index(index_by_qn, module_index)
    edges: list[RawEdge] = []
    for scope in scopes:
        seen: set[tuple] = set()
        _imports(scope, idx, edges, seen)
        _inherits(scope, idx, edges, seen)
        _calls(scope, idx, edges, seen)
    return edges


def _add(
    edges: list[RawEdge],
    seen: set[tuple],
    *,
    kind: DependencyKind,
    src: str,
    target: str,
    dst: str | None,
    line: int | None,
    external: bool,
    attributes: dict | None = None,
) -> None:
    key = (kind.value, src, target, dst)
    if key in seen:
        for e in edges:
            if (e.kind.value, e.src_key, e.target_name, e.dst_key) == key:
                e.attributes["occurrences"] = e.attributes.get("occurrences", 1) + 1
                return
    seen.add(key)
    edges.append(
        RawEdge(
            kind=kind, src_key=src, target_name=target, dst_key=dst,
            external=external and dst is None, source_line=line,
            attributes={"occurrences": 1, **(attributes or {})},
        )
    )


def _imports(scope: ModuleScope, idx: _Index, edges: list[RawEdge], seen: set[tuple]) -> None:
    for target_module, names, line, is_star in scope.imports:
        if not target_module:
            continue
        name_list = [o for o, _ in names]
        dst = idx.module(target_module)
        if dst is not None:
            # module -> module edge; record which imported names landed on components
            resolved_names = [n for n in name_list if idx.symbol(f"{target_module}.{n}")]
            _add(
                edges, seen, kind=DependencyKind.IMPORTS, src=scope.module_key,
                target=target_module, dst=dst, line=line, external=False,
                attributes={"names": name_list, "resolved_names": resolved_names, "star": is_star}
                if name_list or is_star else None,
            )
            continue
        # target module not in the snapshot: maybe `from pkg import submodule`
        emitted = False
        for orig in name_list:
            child = f"{target_module}.{orig}"
            k = idx.module(child)
            if k:
                _add(edges, seen, kind=DependencyKind.IMPORTS, src=scope.module_key,
                     target=child, dst=k, line=line, external=False)
                emitted = True
        if not emitted:
            _add(
                edges, seen, kind=DependencyKind.IMPORTS, src=scope.module_key,
                target=target_module, dst=None, line=line, external=True,
                attributes={"names": name_list, "star": is_star} if name_list or is_star else None,
            )


def _inherits(scope: ModuleScope, idx: _Index, edges: list[RawEdge], seen: set[tuple]) -> None:
    for class_key, base_dotted, line in scope.inherits:
        parts = base_dotted.split(".")
        target_qn: str | None = None
        if len(parts) == 1:
            nm = parts[0]
            if nm in scope.alias_map:
                target_qn = scope.alias_map[nm]
            elif idx.klass(f"{scope.module_qn}.{nm}"):
                target_qn = f"{scope.module_qn}.{nm}"
        else:
            head = parts[0]
            if head in scope.alias_map:
                target_qn = scope.alias_map[head] + "." + ".".join(parts[1:])
        dst = idx.klass(target_qn) if target_qn else None
        _add(edges, seen, kind=DependencyKind.INHERITS, src=class_key,
             target=target_qn or base_dotted, dst=dst, line=line, external=dst is None)


def _calls(scope: ModuleScope, idx: _Index, edges: list[RawEdge], seen: set[tuple]) -> None:
    for src_key, callee_dotted, _base_name, via_self, line in scope.calls:
        parts = callee_dotted.split(".")
        if via_self:
            cls_qn = scope.class_of_component.get(src_key)
            if cls_qn:
                k = idx.method(f"{cls_qn}.{parts[1]}")
                if k:
                    _add(edges, seen, kind=DependencyKind.CALLS, src=src_key,
                         target=f"{cls_qn}.{parts[1]}", dst=k, line=line, external=False)
            continue

        if len(parts) == 1:
            nm = parts[0]
            if nm in scope.alias_map:
                cand = scope.alias_map[nm]
                k = idx.symbol(cand)
                _add(edges, seen, kind=DependencyKind.CALLS, src=src_key,
                     target=cand, dst=k, line=line, external=k is None)
            elif nm in scope.module_defs:
                cand = f"{scope.module_qn}.{nm}"
                k = idx.symbol(cand)
                if k:
                    _add(edges, seen, kind=DependencyKind.CALLS, src=src_key,
                         target=cand, dst=k, line=line, external=False)
        else:
            head = parts[0]
            if head in scope.alias_map:
                cand = scope.alias_map[head] + "." + ".".join(parts[1:])
                k = idx.symbol(cand) or idx.module(cand)
                _add(edges, seen, kind=DependencyKind.CALLS, src=src_key,
                     target=cand, dst=k, line=line, external=k is None)
