"""RunMode.INCREMENTAL stage plan (Phase 19)."""

from __future__ import annotations

from archon.domain.enums import RunMode, Stage
from archon.jobs.state_machine import STAGE_ORDER, stage_index
from archon.pipeline.orchestrator import _INCREMENTAL_STAGES, _STAGE_PLANS
from tests.conftest import terminal_stage

_SANDBOX_OR_AI = {
    Stage.ARCHAEOLOGIZING, Stage.CHARACTERIZING, Stage.GENERATING_TESTS, Stage.EXECUTING,
    Stage.DETECTING_FAILURES, Stage.INVESTIGATING, Stage.GENERATING_PATCH,
    Stage.RANKING_PATCHES, Stage.VERIFYING_PATCH, Stage.REGRESSION_VERIFYING,
    Stage.RECORDING_INCIDENT, Stage.MODERNIZING,
}


def test_incremental_plan_is_registered():
    assert _STAGE_PLANS[RunMode.INCREMENTAL] == _INCREMENTAL_STAGES


def test_incremental_plan_exact_stages():
    assert _INCREMENTAL_STAGES == (
        Stage.INGESTING, Stage.SNAPSHOTTING, Stage.ANALYZING_SOURCE, Stage.ANALYZING_GIT,
        Stage.BUILDING_GRAPH, Stage.RECONSTRUCTING_ARCHITECTURE,
        Stage.ASSESSING_CHANGE_SAFETY, Stage.ANALYZING_CHANGE_IMPACT, Stage.ANALYZING_TESTS,
    )


def test_incremental_plan_is_strictly_increasing_subsequence_of_stage_order():
    idxs = [stage_index(s) for s in _INCREMENTAL_STAGES]
    assert idxs == sorted(idxs)
    assert len(set(idxs)) == len(idxs)
    assert set(_INCREMENTAL_STAGES).issubset(set(STAGE_ORDER))


def test_incremental_plan_is_sandbox_free_and_ai_free():
    assert _SANDBOX_OR_AI.isdisjoint(set(_INCREMENTAL_STAGES))


def test_terminal_stage_resolves():
    assert terminal_stage("INCREMENTAL") is Stage.ANALYZING_TESTS
