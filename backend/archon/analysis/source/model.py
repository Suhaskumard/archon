"""Backend-independent value objects produced by the source extractor."""

from __future__ import annotations

from dataclasses import dataclass, field

from archon.domain.enums import ComponentKind, DependencyKind

EXTRACTOR_VERSION = "source.v1"


@dataclass
class RawComponent:
    key: str                      # unique within one extraction (used to wire edges)
    kind: ComponentKind
    name: str
    qualified_name: str
    path: str                     # repo-relative, posix
    start_line: int | None
    end_line: int | None
    parent_key: str | None
    metrics: dict = field(default_factory=dict)
    attributes: dict = field(default_factory=dict)


@dataclass
class RawEdge:
    kind: DependencyKind
    src_key: str
    target_name: str
    dst_key: str | None = None    # set when resolved to a component in this snapshot
    external: bool = False
    source_line: int | None = None
    attributes: dict = field(default_factory=dict)


@dataclass
class ExtractionResult:
    components: list[RawComponent] = field(default_factory=list)
    edges: list[RawEdge] = field(default_factory=list)
    module_count: int = 0
    file_count: int = 0
    parse_errors: list[dict] = field(default_factory=list)   # {path, message, line}
    skipped: list[dict] = field(default_factory=list)        # {path, reason}
    entrypoints: list[dict] = field(default_factory=list)    # {kind, path, detail, component_key?}
    degraded: bool = False
    degraded_reason: str | None = None

    def counts(self) -> dict[str, int]:
        c = {k.value: 0 for k in ComponentKind}
        for comp in self.components:
            c[comp.kind.value] += 1
        e: dict[str, int] = {}
        resolved = 0
        for edge in self.edges:
            e[edge.kind.value] = e.get(edge.kind.value, 0) + 1
            if edge.dst_key is not None:
                resolved += 1
        return {
            **{f"components.{k}": v for k, v in c.items()},
            **{f"edges.{k}": v for k, v in e.items()},
            "edges.resolved": resolved,
            "edges.total": len(self.edges),
        }
