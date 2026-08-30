"""Engine-version registry (spec sections 5, 6, 53, 60).

Every deterministic engine and AI schema that produces a stored conclusion registers a
version string here. ``AnalysisRun.engine_versions`` snapshots this map at run start so
results are reproducible and cache keys never cross incompatible engine versions.
"""

from __future__ import annotations

# Phase 1 only ships the ingestion pipeline; later phases append their engines here.
ENGINE_VERSIONS: dict[str, str] = {
    "pipeline": "pipeline.v1",
    "ingestion": "ingestion.v1",
    "snapshot": "snapshot.v1",
}


def register(name: str, version: str) -> None:
    existing = ENGINE_VERSIONS.get(name)
    if existing and existing != version:
        raise ValueError(f"engine {name!r} already registered as {existing!r}, not {version!r}")
    ENGINE_VERSIONS[name] = version


def current_versions() -> dict[str, str]:
    return dict(ENGINE_VERSIONS)
