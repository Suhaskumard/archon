"""Explicit analysis state machine (spec section 10).

No "magic status" values: every run-state transition is enumerated in ``RUN_TRANSITIONS``
and every stage order is enumerated in ``STAGE_ORDER``. Illegal transitions raise.
"""

from __future__ import annotations

from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.domain.enums import RunState, Stage

# --- run-level lifecycle ---------------------------------------------------------------

RUN_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.PENDING: frozenset({RunState.QUEUED, RunState.CANCELLED, RunState.FAILED}),
    RunState.QUEUED: frozenset({RunState.RUNNING, RunState.CANCELLED, RunState.FAILED}),
    RunState.RUNNING: frozenset({RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}

TERMINAL_RUN_STATES: frozenset[RunState] = frozenset(
    {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
)

# --- stage ordering ------------------------------------------------------------------
# The full pipeline (spec section 67). Phase 1 executes only the first two stages and
# then completes the run in INGEST_ONLY mode; later phases extend the executed prefix.

STAGE_ORDER: tuple[Stage, ...] = (
    Stage.INGESTING,
    Stage.SNAPSHOTTING,
    Stage.ANALYZING_SOURCE,
    Stage.ANALYZING_GIT,
    Stage.BUILDING_GRAPH,
    Stage.RECONSTRUCTING_ARCHITECTURE,
    Stage.ARCHAEOLOGIZING,
    Stage.SCORING_UNDERSTANDING,
    Stage.BUILDING_LEGACY_DNA,
    Stage.ANALYZING_TECH_DEBT,
    Stage.SCORING_HOTSPOTS,
    Stage.ASSESSING_CHANGE_SAFETY,
    Stage.ANALYZING_CHANGE_IMPACT,
    Stage.ANALYZING_TESTS,
    Stage.CHARACTERIZING,
    Stage.GENERATING_TESTS,
    Stage.EXECUTING,
    Stage.DETECTING_FAILURES,
    Stage.INVESTIGATING,
    Stage.GENERATING_PATCH,
    Stage.RANKING_PATCHES,
    Stage.VERIFYING_PATCH,
    Stage.REGRESSION_VERIFYING,
    Stage.RECORDING_INCIDENT,
    Stage.MODERNIZING,
)

_STAGE_INDEX = {stage: i for i, stage in enumerate(STAGE_ORDER)}


class IllegalTransition(ArchonError):
    def __init__(self, frm: object, to: object) -> None:
        super().__init__(
            ErrorCode.ILLEGAL_STATE_TRANSITION,
            f"illegal transition {getattr(frm, 'value', frm)} -> {getattr(to, 'value', to)}",
            context={"from": getattr(frm, "value", str(frm)), "to": getattr(to, "value", str(to))},
            recoverability=Recoverability.NON_RECOVERABLE,
            suggested_action="This is a pipeline bug - transitions must follow the state machine.",
        )


def next_stage(current: Stage | None) -> Stage | None:
    """Return the stage after ``current`` in canonical order, or None past the end."""
    if current is None:
        return STAGE_ORDER[0]
    idx = _STAGE_INDEX[current]
    return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else None


def stage_index(stage: Stage) -> int:
    return _STAGE_INDEX[stage]


class RunStateMachine:
    """Validates run-state transitions and stage advancement for one run."""

    def __init__(self, state: RunState, stage: Stage | None = None) -> None:
        self.state = state
        self.stage = stage

    def can_transition(self, to: RunState) -> bool:
        return to in RUN_TRANSITIONS.get(self.state, frozenset())

    def transition(self, to: RunState) -> RunState:
        if not self.can_transition(to):
            raise IllegalTransition(self.state, to)
        self.state = to
        return to

    def enter_stage(self, stage: Stage) -> Stage:
        """Advance to ``stage``. Only forward moves along ``STAGE_ORDER`` are allowed."""
        if self.state != RunState.RUNNING:
            raise IllegalTransition(self.state, f"stage:{stage.value}")
        if self.stage is not None and stage_index(stage) <= stage_index(self.stage):
            raise IllegalTransition(self.stage, stage)
        self.stage = stage
        return stage

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_RUN_STATES
