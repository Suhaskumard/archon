import pytest

from archon.core.errors import ArchonError
from archon.domain.enums import RunState, Stage
from archon.jobs.state_machine import (
    STAGE_ORDER,
    IllegalTransition,
    RunStateMachine,
    next_stage,
)


def test_legal_run_lifecycle():
    sm = RunStateMachine(RunState.PENDING)
    sm.transition(RunState.QUEUED)
    sm.transition(RunState.RUNNING)
    sm.transition(RunState.COMPLETED)
    assert sm.is_terminal


@pytest.mark.parametrize(
    "start,target",
    [
        (RunState.PENDING, RunState.RUNNING),
        (RunState.COMPLETED, RunState.RUNNING),
        (RunState.RUNNING, RunState.QUEUED),
    ],
)
def test_illegal_run_transitions_raise(start, target):
    with pytest.raises(IllegalTransition):
        RunStateMachine(start).transition(target)


def test_stage_order_is_forward_only():
    sm = RunStateMachine(RunState.RUNNING)
    sm.enter_stage(Stage.INGESTING)
    sm.enter_stage(Stage.SNAPSHOTTING)
    with pytest.raises(ArchonError):
        sm.enter_stage(Stage.INGESTING)  # cannot go backwards


def test_next_stage_walks_canonical_order():
    assert next_stage(None) is STAGE_ORDER[0]
    assert next_stage(Stage.INGESTING) is Stage.SNAPSHOTTING
    assert next_stage(STAGE_ORDER[-1]) is None


def test_cannot_enter_stage_unless_running():
    with pytest.raises(ArchonError):
        RunStateMachine(RunState.QUEUED).enter_stage(Stage.INGESTING)
