"""AnalysisRun.mode is a plain-VARCHAR EnumString - INCREMENTAL persists, junk raises."""

from __future__ import annotations

import pytest

from archon.db.base import session_scope
from archon.db.models import AnalysisRun, Repository
from archon.domain.enums import ProviderKind, RunMode, RunState


def _repo(session) -> Repository:
    r = Repository(provider=ProviderKind.GITHUB, url="https://github.com/a/b", name="b")
    session.add(r)
    session.flush()
    return r


def test_incremental_mode_round_trips():
    with session_scope() as session:
        run = AnalysisRun(
            repository_id=_repo(session).id, mode=RunMode.INCREMENTAL, state=RunState.PENDING,
            engine_versions={},
        )
        session.add(run)
        session.flush()
        run_id = run.id
    with session_scope() as session:
        assert session.get(AnalysisRun, run_id).mode is RunMode.INCREMENTAL


def test_invalid_mode_string_raises():
    # EnumString validates at the Python boundary; SQLAlchemy wraps the ValueError.
    with pytest.raises(Exception) as e:
        with session_scope() as session:
            session.add(
                AnalysisRun(
                    repository_id=_repo(session).id, mode="NOT_A_MODE", state=RunState.PENDING,
                    engine_versions={},
                )
            )
            session.flush()
    assert "not a valid RunMode" in str(e.value)
