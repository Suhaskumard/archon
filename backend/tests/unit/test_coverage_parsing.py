from archon.db.models import Component
from archon.domain.enums import ComponentKind
from archon.testing.coverage import component_coverage_pct, parse_coverage_xml

_XML = """\
<coverage>
  <packages>
    <package name="pkg">
      <classes>
        <class filename="pkg/mod.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="0"/>
            <line number="3" hits="1"/>
            <line number="4" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


def test_parse_coverage_xml_extracts_hits_and_executable_lines():
    parsed = parse_coverage_xml(_XML)
    fc = parsed["pkg/mod.py"]
    assert fc.executable_lines == {1, 2, 3, 4}
    assert fc.covered_lines == {1, 3, 4}


def test_parse_coverage_xml_empty_or_malformed_is_safe():
    assert parse_coverage_xml("") == {}
    assert parse_coverage_xml("not xml at all <<<") == {}


def _component(path: str, start: int | None, end: int | None) -> Component:
    return Component(
        snapshot_id="snap_x", kind=ComponentKind.FUNCTION, name="f", qualified_name="pkg.mod.f",
        path=path, start_line=start, end_line=end,
    )


def test_component_coverage_pct_full_and_partial():
    file_coverage = parse_coverage_xml(_XML)
    fully_covered = _component("pkg/mod.py", 3, 4)
    assert component_coverage_pct(fully_covered, file_coverage) == 1.0

    partially_covered = _component("pkg/mod.py", 1, 2)
    assert component_coverage_pct(partially_covered, file_coverage) == 0.5


def test_component_coverage_pct_defaults_to_zero_when_absent():
    file_coverage = parse_coverage_xml(_XML)
    missing_file = _component("pkg/other.py", 1, 2)
    assert component_coverage_pct(missing_file, file_coverage) == 0.0

    no_line_range = _component("pkg/mod.py", None, None)
    assert component_coverage_pct(no_line_range, file_coverage) == 0.0
