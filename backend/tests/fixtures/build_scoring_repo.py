"""Build the Phase 5 scoring acceptance fixture repository.

A second, independent fixture from ``build_test_repo``'s ``legacy_shop`` (which Phase 4's
acceptance test pins exact commit-count/churn/age numbers on - adding to it would break
that test). This repo plants:

* a **stable** module (``tax_rules``) - trivial, one commit, fully tested, never touched
  again.
* a **risky** module (``pricing_engine``) - deep nested branching (complexity >= 10), no
  test file, imported by 4 other modules (high fan-in), forced into an import cycle with
  ``discount_rules``, touched by several backdated commits (real churn), and carrying
  planted tech-debt smells: a bare ``except:``, an ``except Exception: pass``, a
  hardcoded ``API_KEY``, and a magic number (``tier == 7``).
* a **documented-exception** module (``shipping_calculator``) - has real churn and
  moderate complexity but *is* tested (a ``TESTED_BY`` edge exists), proving the
  coverage-proxy signal's weight is intentionally small rather than silently suppressing
  risk for a module that merely has *a* test file.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.build_test_repo import _git, _write

_FILES_V1 = {
    "README.md": "# scoring-shop\n\nPhase 5 scoring fixture: a stable module and a risky one.\n",
    "requirements.txt": "attrs>=23.0\n",
    "pyproject.toml": (
        "[project]\nname = \"scoring-shop\"\nversion = \"0.1.0\"\n"
        "requires-python = \">=3.10\"\n"
    ),
    "scoring_shop/__init__.py": "",
    "scoring_shop/tax_rules.py": (
        '"""Tax rules - simple and fully tested (the stable/low-risk fixture module)."""\n\n\n'
        "def calc_tax(amount):\n    return round(amount * 0.1, 2)\n"
    ),
    "tests/__init__.py": "",
    "tests/test_tax_rules.py": (
        "from scoring_shop.tax_rules import calc_tax\n\n\n"
        "def test_calc_tax():\n    assert calc_tax(100) == 10.0\n"
    ),
    "scoring_shop/shipping_calculator.py": (
        '"""Shipping calculator - tested, but still churns and has some complexity\n'
        '(the documented coverage-proxy exception case for Phase 5 scoring tests)."""\n\n\n'
        "def shipping_cost(weight, distance, express):\n"
        "    cost = 5\n"
        "    if weight > 50:\n        cost += 10\n"
        "    elif weight > 20:\n        cost += 5\n"
        "    if distance > 1000:\n        cost += 15\n"
        "    elif distance > 200:\n        cost += 5\n"
        "    if express:\n        cost *= 2\n"
        "    return cost\n"
    ),
    "tests/test_shipping_calculator.py": (
        "from scoring_shop.shipping_calculator import shipping_cost\n\n\n"
        "def test_shipping_cost():\n    assert shipping_cost(10, 100, False) == 5\n"
    ),
    "scoring_shop/discount_rules.py": (
        '"""Discount rules - imports pricing_engine to form a deliberate import cycle."""\n\n'
        "from scoring_shop.pricing_engine import price_for  # noqa: F401 (cycle fixture)\n\n\n"
        "def bulk_discount(qty):\n"
        "    if qty > 500:\n        return 10\n"
        "    if qty > 200:\n        return 5\n"
        "    return 0\n"
    ),
    "scoring_shop/pricing_engine.py": (
        '"""Pricing engine - the deliberately risky fixture module: deep branching,\n'
        'no tests, high fan-in, an import cycle, and planted tech-debt smells."""\n\n'
        "from scoring_shop.discount_rules import bulk_discount\n\n"
        'API_KEY = "sk-hardcoded-demo"\n\n\n'
        "def price_for(tier, qty, region):\n"
        "    base = 10\n"
        "    if tier == 1:\n"
        '        if region == "US":\n            base = 12\n'
        '        elif region == "EU":\n            base = 14\n'
        "        else:\n            base = 16\n"
        "    elif tier == 2:\n"
        '        if region == "US":\n            base = 20\n'
        '        elif region == "EU":\n            base = 22\n'
        "        else:\n            base = 24\n"
        "    elif tier == 7:\n        base = 99\n"
        "    else:\n        base = 10\n\n"
        "    if qty > 100:\n        base = base - bulk_discount(qty)\n"
        "    elif qty > 10:\n        base = base - 1\n"
        "    else:\n        base = base\n\n"
        "    try:\n        base = base - (qty - qty)\n"
        "    except:\n        pass\n\n"
        "    try:\n        base = base + 0\n"
        "    except Exception:\n        pass\n\n"
        "    return base\n"
    ),
    "scoring_shop/checkout.py": (
        '"""Consumer of pricing_engine (inflates its fan-in)."""\n\n'
        "from scoring_shop.pricing_engine import price_for\n\n\n"
        "def checkout_total(items):\n"
        "    total = 0\n"
        "    for _sku, qty in items:\n        total += price_for(1, qty, \"US\")\n"
        "    return total\n"
    ),
    "scoring_shop/invoice.py": (
        '"""Consumer of pricing_engine (inflates its fan-in)."""\n\n'
        "from scoring_shop.pricing_engine import price_for\n\n\n"
        "def invoice_amount(order):\n"
        "    return price_for(order.get(\"tier\", 1), order.get(\"qty\", 1), order.get(\"region\", \"US\"))\n"
    ),
    "scoring_shop/promotions.py": (
        '"""Consumer of pricing_engine (inflates its fan-in)."""\n\n'
        "from scoring_shop.pricing_engine import price_for\n\n\n"
        "def promo_price(tier, qty):\n    return price_for(tier, qty, \"US\") * 0.9\n"
    ),
}

_PRICING_ENGINE_V2 = {
    "scoring_shop/pricing_engine.py": _FILES_V1["scoring_shop/pricing_engine.py"].replace(
        "base = base + 0", "base = base + 0  # tweak v2"
    ),
}
_SHIPPING_V2 = {
    "scoring_shop/shipping_calculator.py": _FILES_V1["scoring_shop/shipping_calculator.py"].replace(
        "cost = 5\n", "cost = 5  # tweak v2\n"
    ),
}
_PRICING_ENGINE_V3 = {
    "scoring_shop/pricing_engine.py": _FILES_V1["scoring_shop/pricing_engine.py"].replace(
        "base = base + 0", "base = base + 0  # tweak v3"
    ),
}
_SHIPPING_V3 = {
    "scoring_shop/shipping_calculator.py": _FILES_V1["scoring_shop/shipping_calculator.py"].replace(
        "cost = 5\n", "cost = 5  # tweak v3\n"
    ),
}
_PRICING_ENGINE_V4 = {
    "scoring_shop/pricing_engine.py": _FILES_V1["scoring_shop/pricing_engine.py"].replace(
        "base = base + 0", "base = base + 0  # tweak v4"
    ),
}


def build_scoring_repo(dest: Path) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], dest)
    _git(["config", "user.email", "fixture@archon.test"], dest)
    _git(["config", "user.name", "ARCHON Fixture"], dest)
    _git(["config", "commit.gpgsign", "false"], dest)

    _write(dest, _FILES_V1)
    _git(["add", "-A"], dest)
    _git(["commit", "-m", "Initial commit: tax_rules, pricing_engine, shipping_calculator"], dest,
         when="2026-01-01T12:00:00")

    _write(dest, _PRICING_ENGINE_V2)
    _git(["add", "-A"], dest)
    _git(["commit", "-m", "Tweak pricing_engine"], dest, when="2026-02-01T12:00:00")

    _write(dest, _SHIPPING_V2)
    _git(["add", "-A"], dest)
    _git(["commit", "-m", "Tweak shipping_calculator"], dest, when="2026-03-01T12:00:00")

    _write(dest, _PRICING_ENGINE_V3)
    _git(["add", "-A"], dest)
    _git(["commit", "-m", "Tweak pricing_engine again"], dest, when="2026-04-01T12:00:00")

    _write(dest, _SHIPPING_V3)
    _git(["add", "-A"], dest)
    _git(["commit", "-m", "Tweak shipping_calculator again"], dest, when="2026-05-01T12:00:00")

    _write(dest, _PRICING_ENGINE_V4)
    _git(["add", "-A"], dest)
    _git(["commit", "-m", "Tweak pricing_engine a third time"], dest, when="2026-06-01T12:00:00")

    return dest


if __name__ == "__main__":  # pragma: no cover
    import sys

    out = build_scoring_repo(Path(sys.argv[1] if len(sys.argv) > 1 else "./_scoring_fixture_repo"))
    print(f"built scoring fixture repo at {out}")
