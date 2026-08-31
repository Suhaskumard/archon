from types import SimpleNamespace

from archon.analysis.scoring.tech_debt_detectors import (
    circular_dependencies,
    dead_code_candidates,
    detect_ast_debt,
    global_state_from_assumptions,
    high_coupling,
    large_classes,
    long_functions,
)


def _comp(kind, **kw):
    defaults = dict(
        id=f"comp-{kw.get('name', 'x')}", name="x", path="mod.py", qualified_name="mod.x",
        start_line=1, metrics={}, is_entrypoint=False, is_test=False, parent_id=None,
    )
    defaults.update(kw)
    defaults["kind"] = SimpleNamespace(value=kind)
    return SimpleNamespace(**defaults)


def _dep(src, dst, kind):
    return SimpleNamespace(src_component_id=src, dst_component_id=dst, kind=kind)


# --- long_functions -------------------------------------------------------------


def test_long_function_detected():
    c = _comp("FUNCTION", name="big", metrics={"loc": 80})
    findings = long_functions([c])
    assert len(findings) == 1
    assert findings[0]["category"] == "LONG_FUNCTION"


def test_short_function_not_flagged():
    c = _comp("FUNCTION", name="small", metrics={"loc": 10})
    assert long_functions([c]) == []


# --- large_classes ----------------------------------------------------------------


def test_large_class_by_method_count():
    cls = _comp("CLASS", name="Big", metrics={"loc": 50})
    methods = [_comp("METHOD", name=f"m{i}", parent_id=cls.id) for i in range(20)]
    findings = large_classes([cls], {cls.id: methods})
    assert len(findings) == 1
    assert findings[0]["category"] == "LARGE_CLASS"


def test_small_class_not_flagged():
    cls = _comp("CLASS", name="Small", metrics={"loc": 20})
    methods = [_comp("METHOD", name="m1", parent_id=cls.id)]
    assert large_classes([cls], {cls.id: methods}) == []


# --- circular_dependencies ---------------------------------------------------------


def test_module_in_cycle_flagged():
    m = _comp("MODULE", name="a", metrics={"architecture": {"in_cycle": True, "scc_size": 2}})
    findings = circular_dependencies([m])
    assert len(findings) == 1
    assert findings[0]["category"] == "CIRCULAR_DEPENDENCY"


def test_module_not_in_cycle_not_flagged():
    m = _comp("MODULE", name="a", metrics={"architecture": {"in_cycle": False}})
    assert circular_dependencies([m]) == []


# --- high_coupling ------------------------------------------------------------------


def test_high_coupling_flagged():
    m = _comp("MODULE", name="hub", metrics={"architecture": {"fan_in": 8, "fan_out": 8}})
    findings = high_coupling([m])
    assert len(findings) == 1


def test_low_coupling_not_flagged():
    m = _comp("MODULE", name="leaf", metrics={"architecture": {"fan_in": 1, "fan_out": 1}})
    assert high_coupling([m]) == []


# --- dead_code_candidates -----------------------------------------------------------


def test_uncalled_function_flagged():
    c = _comp("FUNCTION", name="orphan")
    assert len(dead_code_candidates([c], [])) == 1


def test_called_function_not_flagged():
    c = _comp("FUNCTION", name="used")
    deps = [_dep("caller", c.id, "CALLS")]
    assert dead_code_candidates([c], deps) == []


def test_entrypoint_never_flagged():
    c = _comp("FUNCTION", name="main", is_entrypoint=True)
    assert dead_code_candidates([c], []) == []


# --- global_state_from_assumptions ---------------------------------------------------


def test_global_state_assumption_mapped_to_finding():
    a = SimpleNamespace(
        kind="global_state", description="mutates _STOCK", location="inventory.py:10",
        risk="HIGH", confidence="HIGH", suggested_test="reset before/after", component_id="c1",
    )
    findings = global_state_from_assumptions([a])
    assert len(findings) == 1
    assert findings[0]["category"] == "GLOBAL_STATE"
    assert findings[0]["severity"] == "HIGH"


def test_non_global_state_assumption_ignored():
    a = SimpleNamespace(kind="division", description="x", location="y:1", risk="LOW", confidence="LOW",
                        suggested_test=None, component_id=None)
    assert global_state_from_assumptions([a]) == []


# --- AST-based detectors (duplicate_logic, low_cohesion, deprecated_apis, ------------
# --- hardcoded_config, broad_except, silent_failure, magic_numbers) ------------------


def _write(tmp_path, name, source):
    p = tmp_path / name
    p.write_text(source, encoding="utf-8")
    return p


def test_broad_except_detected(tmp_path):
    _write(tmp_path, "m.py", "def f():\n    try:\n        1/0\n    except:\n        pass\n")
    findings = detect_ast_debt(tmp_path, lambda rel: "m")
    cats = {f["category"] for f in findings}
    assert "BROAD_EXCEPT" in cats
    assert "SILENT_FAILURE" in cats


def test_narrow_except_not_flagged(tmp_path):
    _write(tmp_path, "m.py", "def f():\n    try:\n        1/0\n    except ZeroDivisionError:\n        raise\n")
    findings = detect_ast_debt(tmp_path, lambda rel: "m")
    cats = {f["category"] for f in findings}
    assert "BROAD_EXCEPT" not in cats
    assert "SILENT_FAILURE" not in cats


def test_hardcoded_secret_detected(tmp_path):
    _write(tmp_path, "m.py", 'API_KEY = "sk-hardcoded-demo"\n')
    findings = detect_ast_debt(tmp_path, lambda rel: "m")
    assert any(f["category"] == "HARDCODED_CONFIG" for f in findings)


def test_env_derived_config_not_flagged(tmp_path):
    _write(tmp_path, "m.py", "import os\nAPI_KEY = os.environ.get('API_KEY')\n")
    findings = detect_ast_debt(tmp_path, lambda rel: "m")
    assert not any(f["category"] == "HARDCODED_CONFIG" for f in findings)


def test_magic_number_detected(tmp_path):
    _write(tmp_path, "m.py", "def tier(x):\n    if x == 7:\n        return True\n    return False\n")
    findings = detect_ast_debt(tmp_path, lambda rel: "m")
    assert any(f["category"] == "MAGIC_NUMBER" for f in findings)


def test_zero_and_one_not_magic(tmp_path):
    _write(tmp_path, "m.py", "def f(x):\n    return x == 0 or x == 1\n")
    findings = detect_ast_debt(tmp_path, lambda rel: "m")
    assert not any(f["category"] == "MAGIC_NUMBER" for f in findings)


def test_magic_number_skipped_in_test_files(tmp_path):
    (tmp_path / "tests").mkdir()
    _write(tmp_path / "tests", "test_m.py", "def test_f():\n    assert 42 == 42\n")
    findings = detect_ast_debt(tmp_path, lambda rel: "tests.test_m")
    assert not any(f["category"] == "MAGIC_NUMBER" for f in findings)


def test_deprecated_import_detected(tmp_path):
    _write(tmp_path, "m.py", "import imp\n")
    findings = detect_ast_debt(tmp_path, lambda rel: "m")
    assert any(f["category"] == "DEPRECATED_API" for f in findings)


def test_modern_import_not_flagged(tmp_path):
    _write(tmp_path, "m.py", "import importlib\n")
    findings = detect_ast_debt(tmp_path, lambda rel: "m")
    assert not any(f["category"] == "DEPRECATED_API" for f in findings)


def test_duplicate_logic_detected(tmp_path):
    body = (
        "def a(x):\n"
        "    total = 0\n"
        "    for i in range(x):\n"
        "        if i % 2 == 0:\n"
        "            total += i\n"
        "        else:\n"
        "            total -= i\n"
        "    return total\n\n"
        "def b(y):\n"
        "    total = 0\n"
        "    for i in range(y):\n"
        "        if i % 2 == 0:\n"
        "            total += i\n"
        "        else:\n"
        "            total -= i\n"
        "    return total\n"
    )
    _write(tmp_path, "m.py", body)
    findings = detect_ast_debt(tmp_path, lambda rel: "m")
    assert sum(1 for f in findings if f["category"] == "DUPLICATE_LOGIC") == 2


def test_distinct_functions_not_flagged_as_duplicate(tmp_path):
    _write(tmp_path, "m.py", "def a(x):\n    return x + 1\n\ndef b(y):\n    return y * 2\n")
    findings = detect_ast_debt(tmp_path, lambda rel: "m")
    assert not any(f["category"] == "DUPLICATE_LOGIC" for f in findings)


def test_low_cohesion_detected(tmp_path):
    body = (
        "class Mixed:\n"
        "    def __init__(self):\n"
        "        self.a = 1\n"
        "        self.b = 2\n"
        "    def use_a(self):\n"
        "        return self.a\n"
        "    def touch_a(self):\n"
        "        self.a += 1\n"
        "    def use_b(self):\n"
        "        return self.b\n"
    )
    _write(tmp_path, "m.py", body)
    findings = detect_ast_debt(tmp_path, lambda rel: "m")
    assert any(f["category"] == "LOW_COHESION" for f in findings)


def test_cohesive_class_not_flagged(tmp_path):
    body = (
        "class Cohesive:\n"
        "    def __init__(self):\n"
        "        self.a = 1\n"
        "    def use_a(self):\n"
        "        return self.a\n"
        "    def touch_a(self):\n"
        "        self.a += 1\n"
        "    def double_a(self):\n"
        "        return self.a * 2\n"
    )
    _write(tmp_path, "m.py", body)
    findings = detect_ast_debt(tmp_path, lambda rel: "m")
    assert not any(f["category"] == "LOW_COHESION" for f in findings)
