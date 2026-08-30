"""Unit tests for the AST extractor over a small synthetic tree (spec section 22)."""

from __future__ import annotations

from pathlib import Path

import pytest

from archon.analysis.source import extract_repository
from archon.domain.enums import ComponentKind


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


@pytest.fixture
def sample(tmp_path):
    return _tree(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname="x"\n[project.scripts]\nx-cli = "app.cli:main"\n',
            "app/__init__.py": "",
            "app/util.py": "def helper(a, b):\n    return a + b\n",
            "app/core.py": (
                "from app.util import helper\n"
                "import os\n\n"
                "GLOBAL = 1\n\n"
                "class Base:\n"
                "    def run(self):\n"
                "        return helper(1, 2)\n\n"
                "class Child(Base):\n"
                "    def run(self):\n"
                "        if GLOBAL:\n"
                "            return self.helper2()\n"
                "        return super().run()\n\n"
                "    def helper2(self):\n"
                "        return os.getpid()\n"
            ),
            "app/cli.py": (
                "from app.core import Child\n\n"
                "def main():\n"
                "    return Child().run()\n\n"
                'if __name__ == "__main__":\n'
                "    main()\n"
            ),
        },
    )


def test_component_inventory(sample):
    res = extract_repository(sample)
    by_kind: dict[str, set[str]] = {k.value: set() for k in ComponentKind}
    for c in res.components:
        by_kind[c.kind.value].add(c.qualified_name)

    assert by_kind["MODULE"] == {"app", "app.util", "app.core", "app.cli"}
    assert by_kind["CLASS"] == {"app.core.Base", "app.core.Child"}
    assert {"app.core.Base.run", "app.core.Child.run", "app.core.Child.helper2"} <= by_kind["METHOD"]
    assert {"app.util.helper", "app.cli.main"} <= by_kind["FUNCTION"]
    assert "pyproject.toml" in by_kind["FILE"]


def test_edges_resolved(sample):
    res = extract_repository(sample)
    edges = {(e.kind.value, _qn(res, e.src_key), e.target_name, e.dst_key is not None) for e in res.edges}

    assert ("IMPORTS", "app.core", "app.util", True) in edges
    assert ("IMPORTS", "app.core", "os", False) in edges          # stdlib -> unresolved/external
    assert ("INHERITS", "app.core.Child", "app.core.Base", True) in edges
    assert ("CALLS", "app.core.Base.run", "app.util.helper", True) in edges
    assert ("CALLS", "app.core.Child.run", "app.core.Child.helper2", True) in edges  # self.helper2()
    assert ("CALLS", "app.cli.main", "app.core.Child", True) in edges  # Child() constructor


def test_metrics_and_flags(sample):
    res = extract_repository(sample)
    child_run = next(c for c in res.components if c.qualified_name == "app.core.Child.run")
    assert child_run.kind is ComponentKind.METHOD
    assert child_run.metrics["complexity"] == 2  # one `if`
    assert child_run.metrics["param_count"] == 1  # self
    assert child_run.metrics["complexity_model"] == "complexity.v1"

    core = next(c for c in res.components if c.qualified_name == "app.core" and c.kind is ComponentKind.MODULE)
    assert core.attributes["is_package"] is False
    assert core.attributes["is_test"] is False


def test_entrypoints_detected(sample):
    res = extract_repository(sample)
    kinds = {e["kind"] for e in res.entrypoints}
    assert "main_guard" in kinds          # if __name__ == "__main__"
    assert "console_script" in kinds      # pyproject [project.scripts]
    # the console script points at app.cli:main
    cs = next(e for e in res.entrypoints if e["kind"] == "console_script")
    assert cs["component_key"] == "fn:app.cli.main"


def test_syntax_error_is_recorded_not_raised(tmp_path):
    _tree(tmp_path, {"broken.py": "def oops(:\n    pass\n", "ok.py": "x = 1\n"})
    res = extract_repository(tmp_path)
    assert len(res.parse_errors) == 1
    assert res.parse_errors[0]["path"] == "broken.py"
    # module component still exists, flagged
    broken = next(c for c in res.components if c.qualified_name == "broken")
    assert "parse_error" in broken.attributes


def _qn(res, key: str) -> str:
    for c in res.components:
        if c.key == key:
            return c.qualified_name
    return key
