"""Hidden-assumption heuristics: fire on a clear instance, stay quiet when guarded
(spec section 26)."""

from __future__ import annotations

from pathlib import Path

from archon.analysis.archaeology.assumptions import detect_assumptions


def _scan(tmp_path: Path, code: str, name: str = "m.py") -> list:
    (tmp_path / name).write_text(code, encoding="utf-8")
    return detect_assumptions(tmp_path, lambda rel: rel[:-3].replace("/", "."))


def _kinds(found) -> set[str]:
    return {a.kind for a in found}


def test_division(tmp_path):
    assert "division" in _kinds(_scan(tmp_path, "def f(a, b):\n    return a / b\n"))
    # guarded: divisor is a literal / expression, not a bare param
    assert "division" not in _kinds(_scan(tmp_path, "def f(a):\n    return a / 2\n"))


def test_global_state_and_dict_key(tmp_path):
    code = (
        "_S = {}\n\n"
        "def add(k, n):\n    _S[k] = _S.get(k, 0) + n\n\n"
        "def take(k, n):\n    if _S.get(k, 0) < n:\n        raise ValueError('x')\n    _S[k] -= n\n"
    )
    found = _scan(tmp_path, code)
    assert "global_state" in _kinds(found)
    assert "dict_key" in _kinds(found)
    # dict_key only on the AugAssign in `take`, not the plain Assign in `add`
    dk = [a for a in found if a.kind == "dict_key"]
    assert len(dk) == 1 and dk[0].function_qn.endswith(".take")


def test_dict_key_quiet_when_membership_checked(tmp_path):
    code = "def f(d, k):\n    if k in d:\n        d[k] -= 1\n"
    assert "dict_key" not in _kinds(_scan(tmp_path, code))


def test_environment(tmp_path):
    assert "environment" in _kinds(
        _scan(tmp_path, "import os\n\ndef f():\n    return os.environ['X']\n")
    )
    assert "environment" in _kinds(
        _scan(tmp_path, "import os\n\ndef f():\n    return os.getenv('X')\n")
    )
    assert "environment" not in _kinds(
        _scan(tmp_path, "import os\n\ndef f():\n    return os.getenv('X', 'default')\n")
    )


def test_timezone(tmp_path):
    assert "timezone" in _kinds(
        _scan(tmp_path, "import datetime\n\ndef f():\n    return datetime.datetime.now()\n")
    )
    assert "timezone" not in _kinds(
        _scan(tmp_path, "import datetime\n\ndef f(tz):\n    return datetime.datetime.now(tz=tz)\n")
    )


def test_empty_collection(tmp_path):
    assert "empty_collection" in _kinds(_scan(tmp_path, "def f(xs):\n    return xs[0]\n"))
    assert "empty_collection" in _kinds(_scan(tmp_path, "def f(xs):\n    return max(xs)\n"))
    assert "empty_collection" not in _kinds(
        _scan(tmp_path, "def f(xs):\n    if xs:\n        return xs[0]\n    return None\n")
    )


def test_null_deref(tmp_path):
    assert "null" in _kinds(_scan(tmp_path, "def f(obj):\n    return obj.value\n"))
    assert "null" not in _kinds(
        _scan(tmp_path, "def f(obj):\n    if obj is None:\n        return 0\n    return obj.value\n")
    )
    # `self` is never flagged
    assert "null" not in _kinds(
        _scan(tmp_path, "class C:\n    def m(self):\n        return self.x\n")
    )


def test_clean_module_is_quiet(tmp_path):
    code = (
        "def add(a, b):\n"
        "    return a + b\n\n\n"
        "def safe_div(a, b):\n"
        "    if b == 0:\n        return None\n"
        "    return a / b\n"
    )
    assert _scan(tmp_path, code) == []
