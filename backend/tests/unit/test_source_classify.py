import pytest

from archon.analysis.source.classify import (
    is_config_path,
    is_test_path,
    module_imports_test_framework,
)


@pytest.mark.parametrize(
    "path,expected",
    [
        ("tests/test_foo.py", True),
        ("pkg/tests/helpers.py", True),
        ("pkg/test_bar.py", True),
        ("pkg/bar_test.py", True),
        ("conftest.py", True),
        ("pkg/module.py", False),
        ("src/app/main.py", False),
    ],
)
def test_is_test_path(path, expected):
    assert is_test_path(path) is expected


@pytest.mark.parametrize(
    "path,expected",
    [
        ("pyproject.toml", True),
        ("setup.cfg", True),
        ("requirements-dev.txt", True),
        ("tox.ini", True),
        ("config/settings.yaml", True),
        ("Dockerfile", True),
        (".env.local", True),
        ("pkg/module.py", False),
        ("README.md", False),
    ],
)
def test_is_config_path(path, expected):
    assert is_config_path(path) is expected


def test_module_imports_test_framework():
    assert module_imports_test_framework({"pytest", "os"}) is True
    assert module_imports_test_framework({"os", "sys"}) is False
