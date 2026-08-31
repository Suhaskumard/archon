from archon.failure.detection import _node_id, _parse_frames, _parse_junit_failures

_JUNIT = """\
<testsuites>
  <testsuite name="pytest" tests="2" failures="1" errors="0">
    <testcase classname="tests.test_calculator" name="test_add" time="0.001"/>
    <testcase classname="tests.test_calculator" name="test_divide_by_zero_returns_none" time="0.002">
      <failure message="ZeroDivisionError: division by zero">tests/test_calculator.py:5: in test_divide_by_zero_returns_none
    assert divide(10, 0) is None
legacy_shop/calculator.py:10: in divide
    return a / b
E   ZeroDivisionError: division by zero</failure>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_parse_junit_failures_extracts_only_failing_testcases():
    failures = _parse_junit_failures(_JUNIT)
    assert len(failures) == 1
    f = failures[0]
    assert f["test_identifier"] == "tests.test_calculator.test_divide_by_zero_returns_none"
    assert f["exception_type"] == "ZeroDivisionError"
    assert "division by zero" in f["message"]


def test_parse_junit_failures_empty_and_malformed_are_safe():
    assert _parse_junit_failures("") == []
    assert _parse_junit_failures("<not-xml") == []


def test_parse_frames_extracts_path_line_func_in_order():
    failures = _parse_junit_failures(_JUNIT)
    frames = _parse_frames(failures[0]["text"])
    assert frames == [
        {"path": "tests/test_calculator.py", "line": 5, "func": "test_divide_by_zero_returns_none"},
        {"path": "legacy_shop/calculator.py", "line": 10, "func": "divide"},
    ]


def test_node_id_converts_junit_identifier_to_pytest_nodeid():
    assert _node_id("tests.test_calculator.test_divide_by_zero_returns_none") == (
        "tests/test_calculator.py::test_divide_by_zero_returns_none"
    )
    assert _node_id("legacy_shop.calculator.test_add") == "legacy_shop/calculator.py::test_add"
