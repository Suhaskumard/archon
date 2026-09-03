"""A mixed-language fixture (spec section 16-17).

Python is a minority of the code files, so ``assess_support`` returns
``PARTIALLY_SUPPORTED``: ARCHON analyses the Python and *summarises* the JS / Go / Shell
rest via a ``NON_PYTHON_SUMMARY`` evidence row rather than ignoring it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_FILES = {
    "README.md": "# polyglot-svc\n\nA small mixed-language service.\n",
    "pyproject.toml": '[project]\nname = "polyglot-svc"\nversion = "0.1.0"\n',
    # --- the Python slice ARCHON actually analyses ---
    "svc/__init__.py": '__version__ = "0.1.0"\n',
    "svc/pricing.py": (
        '"""Pricing helpers (the analysed Python)."""\n\n\n'
        "def total(unit, qty):\n    return unit * qty\n\n\n"
        "def unit_price(amount, qty):\n"
        "    if qty == 0:\n        return None\n"
        "    return amount / qty\n"
    ),
    "tests/test_pricing.py": (
        "from svc.pricing import total\n\n\n"
        "def test_total():\n    assert total(10, 3) == 30\n"
    ),
    # --- the non-Python majority (summarised only) ---
    "web/app.js": "export function render(x){ return `<b>${x}</b>`; }\n",
    "web/util.js": "export const clamp = (n, lo, hi) => Math.max(lo, Math.min(n, hi));\n",
    "web/api.ts": "export type Money = number;\nexport const zero: Money = 0;\n",
    "cmd/server/main.go": "package main\n\nfunc main() { println(\"up\") }\n",
    "cmd/server/route.go": "package main\n\nfunc route(p string) string { return p }\n",
    "scripts/deploy.sh": "#!/bin/sh\nset -e\necho deploying\n",
}


def _git(args: list[str], cwd: Path, when: str | None = None) -> None:
    env = None
    if when is not None:
        import os

        env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env)


def build_polyglot_repo(dest: Path) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], dest)
    _git(["config", "user.email", "fixture@archon.test"], dest)
    _git(["config", "user.name", "ARCHON Fixture"], dest)
    _git(["config", "commit.gpgsign", "false"], dest)
    for rel, content in _FILES.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git(["add", "-A"], dest)
    _git(["commit", "-m", "polyglot service: python pricing + js/ts/go/sh"], dest,
         when="2026-06-01T12:00:00")
    _git(["commit", "--allow-empty", "-m", "second commit for history"], dest,
         when="2026-07-01T12:00:00")
    return dest
