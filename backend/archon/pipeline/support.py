"""MVP supported-repository classification (spec section 17).

Deterministic scan of a checkout. Phase 1 uses this only to label the snapshot and to
record why - it never silently rejects; an UNSUPPORTED result still yields a snapshot with
an explanatory note, and the API surfaces it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from archon.domain.enums import SupportLevel

_DEP_MANIFESTS = ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile")
_TEST_MARKERS = ("pytest.ini", "tox.ini", "conftest.py")
_CODE_EXT = {".py", ".js", ".ts", ".java", ".go", ".rb", ".rs", ".c", ".cpp", ".cs", ".php"}


@dataclass
class SupportAssessment:
    level: SupportLevel
    python_file_count: int
    total_code_file_count: int
    python_ratio: float
    has_dependency_manifest: bool
    has_tests: bool
    has_git_history: bool
    reasons: list[str] = field(default_factory=list)

    def as_notes(self) -> dict:
        return {
            "level": self.level.value,
            "python_file_count": self.python_file_count,
            "total_code_file_count": self.total_code_file_count,
            "python_ratio": round(self.python_ratio, 4),
            "has_dependency_manifest": self.has_dependency_manifest,
            "has_tests": self.has_tests,
            "has_git_history": self.has_git_history,
            "reasons": self.reasons,
        }


def assess_support(repo_dir: Path, *, commit_count: int) -> SupportAssessment:
    py = 0
    code = 0
    has_tests = False
    for _root, dirs, files in os.walk(repo_dir):
        if ".git" in dirs:
            dirs.remove(".git")
        for name in files:
            ext = Path(name).suffix.lower()
            if ext in _CODE_EXT:
                code += 1
                if ext == ".py":
                    py += 1
            if name in _TEST_MARKERS or (name.startswith("test_") and ext == ".py"):
                has_tests = True

    ratio = (py / code) if code else 0.0
    has_manifest = any((repo_dir / m).exists() for m in _DEP_MANIFESTS)
    has_history = commit_count > 1
    reasons: list[str] = []

    if py == 0:
        reasons.append("no Python source files found")
        level = SupportLevel.UNSUPPORTED
    elif ratio >= 0.5 and has_manifest and has_history:
        level = SupportLevel.SUPPORTED
    else:
        level = SupportLevel.PARTIALLY_SUPPORTED
        if ratio < 0.5:
            reasons.append(f"Python is {ratio:.0%} of code files (<50%); non-Python parts summarised only")
        if not has_manifest:
            reasons.append("no dependency manifest; execution will be best-effort")
        if not has_history:
            reasons.append("shallow or single-commit history; archaeology will be degraded")
    if not has_tests and level != SupportLevel.UNSUPPORTED:
        reasons.append("no existing tests discovered; characterization/generation only for baselines")

    return SupportAssessment(
        level=level,
        python_file_count=py,
        total_code_file_count=code,
        python_ratio=ratio,
        has_dependency_manifest=has_manifest,
        has_tests=has_tests,
        has_git_history=has_history,
        reasons=reasons,
    )
