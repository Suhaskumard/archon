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
    # Phase 5 - legacy DNA, tech debt, hotspots, understanding
    "legacy_risk": "legacy_risk.v1",
    "hotspot": "hotspot.v1",
    "understanding": "understanding.v1",
    "tech_debt": "tech_debt.v1",
    # Phase 6 - change safety & change impact
    "change_safety": "change_safety.v1",
    "change_impact": "change_impact.v1",
    # Phase 7 - secure execution / sandbox
    "test_discovery": "test_discovery.v1",
    "execution": "execution.v1",
    # Phase 8 - characterization & test-gap analysis
    "characterization": "characterization.v1",
    "test_generation": "test_generation.v1",
    "coverage_analysis": "coverage_analysis.v1",
    "test_gap_analysis": "test_gap_analysis.v1",
    "ai_test_generation": "test_generation.v1",
    # Phase 9 - failure investigation & self-healing
    "failure_detection": "failure_detection.v1",
    "investigation": "investigation.v1",
    "ai_root_cause_analysis": "root_cause_analysis.v1",
    "patch_generation": "patch_generation.v1",
    "ai_patch_proposal": "patch_proposal.v1",
    "patch_ranking": "patch_ranking.v1",
    "patch_verification": "patch_verification.v1",
}


def register(name: str, version: str) -> None:
    existing = ENGINE_VERSIONS.get(name)
    if existing and existing != version:
        raise ValueError(f"engine {name!r} already registered as {existing!r}, not {version!r}")
    ENGINE_VERSIONS[name] = version


def current_versions() -> dict[str, str]:
    from archon.config import get_settings

    return {**ENGINE_VERSIONS, "ai_provider": get_settings().ai_provider}
