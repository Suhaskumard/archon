"""Build the ARCHON acceptance fixture repository (spec section 57).

Creates a *real* git repository (real commits, real history) with:

* multiple modules with import + call relationships,
* a dependency manifest and existing tests (-> SUPPORTED),
* a deliberate, reproducible bug in ``calculator.divide`` (ZeroDivision path is
  mishandled) that later phases use for failure-investigation / self-healing,
* a known test gap (``inventory.reserve`` has no test).

Phase 1 only needs the repo to exist with history; later phases exercise the bug.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_FILES_V1 = {
    "README.md": "# legacy-shop\n\nA small legacy inventory + billing toy system.\n",
    "requirements.txt": "attrs>=23.0\n",
    "pyproject.toml": (
        "[project]\nname = \"legacy-shop\"\nversion = \"0.1.0\"\n"
        "requires-python = \">=3.10\"\n"
    ),
    "legacy_shop/__init__.py": '__version__ = "0.1.0"\n',
    "legacy_shop/calculator.py": (
        '"""Arithmetic helpers used by billing."""\n\n\n'
        "def add(a, b):\n    return a + b\n\n\n"
        "def divide(a, b):\n"
        "    # BUG: no guard for b == 0; callers expect None on divide-by-zero\n"
        "    return a / b\n"
    ),
    "legacy_shop/billing.py": (
        '"""Billing sits on top of calculator."""\n\n'
        "from legacy_shop.calculator import add, divide\n\n\n"
        "def line_total(unit_price, qty):\n    return add(0, unit_price * qty)\n\n\n"
        "def unit_price(total, qty):\n"
        "    # expected contract: return None when qty is 0\n"
        "    return divide(total, qty)\n"
    ),
    "tests/__init__.py": "",
    "tests/test_calculator.py": (
        "from legacy_shop.calculator import add\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
    ),
}

_FILES_V2 = {
    "legacy_shop/inventory.py": (
        '"""Inventory tracking - added later in history."""\n\n'
        "from legacy_shop.billing import line_total\n\n\n"
        "_STOCK = {}\n\n\n"
        "def restock(sku, amount):\n    _STOCK[sku] = _STOCK.get(sku, 0) + amount\n    return _STOCK[sku]\n\n\n"
        "def reserve(sku, amount):\n"
        "    # KNOWN TEST GAP: no test covers this function\n"
        "    if _STOCK.get(sku, 0) < amount:\n        raise ValueError('insufficient stock')\n"
        "    _STOCK[sku] -= amount\n    return line_total(1, amount)\n"
    ),
    "legacy_shop/orders.py": (
        '"""Order objects - exercises classes, methods and inheritance."""\n\n'
        "from legacy_shop.billing import line_total, unit_price\n\n\n"
        "class Order:\n"
        "    def __init__(self, sku, qty, price):\n"
        "        self.sku = sku\n        self.qty = qty\n        self.price = price\n\n"
        "    def total(self):\n        return line_total(self.price, self.qty)\n\n"
        "    def average(self, paid):\n        return unit_price(paid, self.qty)\n\n\n"
        "class RushOrder(Order):\n"
        "    SURCHARGE = 5\n\n"
        "    def total(self):\n"
        "        base = super().total()\n"
        "        if base is None:\n            return self.SURCHARGE\n"
        "        return base + self.SURCHARGE\n"
    ),
    "tests/test_billing.py": (
        "from legacy_shop.billing import line_total\n\n\n"
        "def test_line_total():\n    assert line_total(10, 3) == 30\n"
    ),
}

_FILES_V3 = {
    "legacy_shop/billing.py": (
        '"""Billing sits on top of calculator."""\n\n'
        "from legacy_shop.calculator import add, divide\n\n\n"
        "def line_total(unit_price, qty):\n    return add(0, unit_price * qty)\n\n\n"
        "def unit_price(total, qty):\n"
        "    # expected contract: return None when qty is 0\n"
        "    if qty == 0:\n        return None\n"
        "    return divide(total, qty)\n"
    ),
}


def _git(args: list[str], cwd: Path, when: str | None = None) -> None:
    env = None
    if when is not None:
        import os

        env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env
    )


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def build_test_repo(dest: Path) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], dest)
    _git(["config", "user.email", "fixture@archon.test"], dest)
    _git(["config", "user.name", "ARCHON Fixture"], dest)
    _git(["config", "commit.gpgsign", "false"], dest)

    # Commits are backdated so churn / age / co-change carry real signal.
    _write(dest, _FILES_V1)
    _git(["add", "-A"], dest)
    _git(["commit", "-m", "Initial commit: calculator + billing + one test"], dest,
         when="2026-06-01T12:00:00")

    _write(dest, _FILES_V2)
    _git(["add", "-A"], dest)
    _git(["commit", "-m", "Add inventory + orders modules and billing test"], dest,
         when="2026-07-01T12:00:00")

    _write(dest, _FILES_V3)
    _git(["add", "-A"], dest)
    _git(["commit", "-m", "Guard unit_price against qty == 0"], dest,
         when="2026-08-01T12:00:00")

    return dest


if __name__ == "__main__":  # pragma: no cover
    import sys

    out = build_test_repo(Path(sys.argv[1] if len(sys.argv) > 1 else "./_fixture_repo"))
    print(f"built fixture repo at {out}")
