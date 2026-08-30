"""Engine-version registry (spec sections 5, 6, 53, 60).

Every deterministic engine and AI schema that produces a stored conclusion registers a
version string here. ``AnalysisRun.engine_versions`` snapshots this map at run start so
results are reproducible and cache keys never cross incompatible engine versions.
"""

from __future__ import annotations

# Each phase appends the engines it introduces. Snapshotted onto every AnalysisRun.
ENGINE_VERSIONS: dict[str, str] = {
    "pipeline": "pipeline.v1",
    "ingestion": "ingestion.v1",
    "snapshot": "snapshot.v1",
    # Phase 2 - source intelligence
    "source": "source.v1",
    "complexity": "complexity.v1",
    # Phase 3 - architecture & dependency intelligence
    "graph": "graph.v1",
    "roles": "roles.v1",
    "arch_metrics": "arch_metrics.v1",
    "architecture": "architecture.v1",
    # Phase 4 - software archaeology
    "git": "git.v1",
    "behavior": "behavior.v1",
    "assumptions": "assumptions.v1",
    "archaeology": "archaeology.v1",
    "ai_historical_intent": "historical_intent.v1",
    "ai_behavior_analysis": "behavior_analysis.v1",
    "ai_assumption_analysis": "assumption_analysis.v1",
}


def register(name: str, version: str) -> None:
    existing = ENGINE_VERSIONS.get(name)
    if existing and existing != version:
        raise ValueError(f"engine {name!r} already registered as {existing!r}, not {version!r}")
    ENGINE_VERSIONS[name] = version


def current_versions() -> dict[str, str]:
    from archon.config import get_settings

    return {**ENGINE_VERSIONS, "ai_provider": get_settings().ai_provider}
