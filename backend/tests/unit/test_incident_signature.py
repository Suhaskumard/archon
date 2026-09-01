from archon.db.models import Failure
from archon.incidents.store import compute_failure_signature


def _failure(exception_type: str, frames: list[dict]) -> Failure:
    return Failure(
        run_id="run_x", execution_id="xrun_x", test_identifier="tests.test_mod.test_f",
        message="boom", exception_type=exception_type, parsed_frames=frames,
        produced_by="failure_detection.v1",
    )


def test_signature_is_deterministic_for_same_failure():
    frames = [{"path": "pkg/mod.py", "line": 5, "func": "f"}, {"path": "pkg/util.py", "line": 10, "func": "g"}]
    a = compute_failure_signature(_failure("ZeroDivisionError", frames))
    b = compute_failure_signature(_failure("ZeroDivisionError", frames))
    assert a == b


def test_signature_ignores_line_numbers():
    frames_v1 = [{"path": "pkg/util.py", "line": 10, "func": "g"}]
    frames_v2 = [{"path": "pkg/util.py", "line": 99, "func": "g"}]  # same file/func, later commit
    a = compute_failure_signature(_failure("ZeroDivisionError", frames_v1))
    b = compute_failure_signature(_failure("ZeroDivisionError", frames_v2))
    assert a == b


def test_signature_differs_for_different_exception_type():
    frames = [{"path": "pkg/util.py", "line": 10, "func": "g"}]
    a = compute_failure_signature(_failure("ZeroDivisionError", frames))
    b = compute_failure_signature(_failure("ValueError", frames))
    assert a != b


def test_signature_differs_for_different_innermost_frame():
    a = compute_failure_signature(_failure("ZeroDivisionError", [{"path": "pkg/a.py", "line": 1, "func": "f"}]))
    b = compute_failure_signature(_failure("ZeroDivisionError", [{"path": "pkg/b.py", "line": 1, "func": "f"}]))
    assert a != b


def test_signature_handles_no_frames():
    assert compute_failure_signature(_failure("RuntimeError", []))
