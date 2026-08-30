"""File classification: test files and configuration files (spec section 22)."""

from __future__ import annotations

from pathlib import PurePosixPath

_TEST_DIR_NAMES = {"tests", "test", "testing"}
_TEST_IMPORTS = {"pytest", "unittest", "nose", "hypothesis"}

_CONFIG_NAMES = {
    "pyproject.toml", "setup.py", "setup.cfg", "pipfile", "pipfile.lock",
    "tox.ini", "pytest.ini", "manifest.in", "makefile", "dockerfile",
    "requirements.txt", "requirements-dev.txt", "constraints.txt",
    ".flake8", ".pylintrc", ".pre-commit-config.yaml", "mypy.ini", "ruff.toml",
}
_CONFIG_SUFFIXES = {".ini", ".cfg", ".toml", ".yaml", ".yml"}
_CONFIG_PREFIXES = ("requirements", "docker-compose", ".env")


def is_test_path(rel_path: str) -> bool:
    p = PurePosixPath(rel_path)
    name = p.name
    if name == "conftest.py":
        return True
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True
    return any(part.lower() in _TEST_DIR_NAMES for part in p.parts[:-1])


def module_imports_test_framework(imported_roots: set[str]) -> bool:
    return bool(imported_roots & _TEST_IMPORTS)


def is_config_path(rel_path: str) -> bool:
    p = PurePosixPath(rel_path)
    name = p.name.lower()
    if name in _CONFIG_NAMES:
        return True
    if any(name.startswith(pref) for pref in _CONFIG_PREFIXES):
        return True
    if p.suffix.lower() in _CONFIG_SUFFIXES:
        return True
    return False
