from archon.domain.enums import SupportLevel
from archon.pipeline.support import assess_support


def test_supported_python_repo(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n")
    (tmp_path / "pkg" / "b.py").write_text("y = 2\n")
    (tmp_path / "requirements.txt").write_text("attrs\n")
    (tmp_path / "test_a.py").write_text("def test_a():\n    assert True\n")

    got = assess_support(tmp_path, commit_count=5)
    assert got.level is SupportLevel.SUPPORTED
    assert got.python_ratio == 1.0
    assert got.has_tests and got.has_dependency_manifest and got.has_git_history


def test_no_python_is_unsupported(tmp_path):
    (tmp_path / "main.js").write_text("console.log(1)\n")
    got = assess_support(tmp_path, commit_count=3)
    assert got.level is SupportLevel.UNSUPPORTED
    assert "no Python source files found" in got.reasons


def test_python_without_manifest_or_history_is_partial(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    got = assess_support(tmp_path, commit_count=1)
    assert got.level is SupportLevel.PARTIALLY_SUPPORTED
    assert any("history" in r for r in got.reasons)
    assert any("dependency manifest" in r for r in got.reasons)
