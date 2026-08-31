import ast

from archon.db.models import Component
from archon.domain.enums import ComponentKind
from archon.testing.characterization import (
    _find_function_node,
    _module_dotted_path,
    assess_target_safety,
    generate_bounded_inputs,
)


def _component(name: str, start_line: int) -> Component:
    return Component(
        snapshot_id="snap_x", kind=ComponentKind.FUNCTION, name=name,
        qualified_name=f"pkg.mod.{name}", path="pkg/mod.py", start_line=start_line, end_line=start_line + 2,
    )


def test_module_dotted_path():
    assert _module_dotted_path("legacy_shop/inventory.py") == "legacy_shop.inventory"
    assert _module_dotted_path("pkg/sub/mod.py") == "pkg.sub.mod"


def test_safe_plain_function_is_accepted():
    source = "def reserve(sku, amount):\n    return sku, amount\n"
    node = _find_function_node(source, "reserve", 1)
    comp = _component("reserve", 1)
    safe, reason = assess_target_safety(comp, source, node)
    assert safe, reason


def test_function_with_banned_construct_is_rejected():
    source = "def leak(x):\n    import subprocess\n    subprocess.run(['ls'])\n"
    node = _find_function_node(source, "leak", 1)
    comp = _component("leak", 1)
    safe, reason = assess_target_safety(comp, source, node)
    assert not safe
    assert "side-effecting" in reason


def test_decorated_function_is_rejected():
    source = "@staticmethod\ndef f(x):\n    return x\n"
    node = _find_function_node(source, "f", 2)
    comp = _component("f", 2)
    safe, reason = assess_target_safety(comp, source, node)
    assert not safe
    assert "decorated" in reason


def test_varargs_function_is_rejected():
    source = "def f(*args, **kwargs):\n    return args\n"
    node = _find_function_node(source, "f", 1)
    comp = _component("f", 1)
    safe, reason = assess_target_safety(comp, source, node)
    assert not safe
    assert "out of scope" in reason


def test_missing_function_node_is_rejected():
    comp = _component("missing", 5)
    safe, reason = assess_target_safety(comp, "def other():\n    pass\n", None)
    assert not safe
    assert "could not locate" in reason


def test_generate_bounded_inputs_is_deterministic_and_uniform_per_param():
    source = "def reserve(sku, amount):\n    return sku, amount\n"
    node = ast.parse(source).body[0]
    inputs_a = generate_bounded_inputs(node)
    inputs_b = generate_bounded_inputs(node)
    assert inputs_a == inputs_b  # reproducible
    assert all(set(inp.keys()) == {"sku", "amount"} for inp in inputs_a)
    assert all(inp["sku"] == inp["amount"] for inp in inputs_a)  # uniform value per input set


def test_generate_bounded_inputs_no_params():
    source = "def f():\n    return 1\n"
    node = ast.parse(source).body[0]
    assert generate_bounded_inputs(node) == [{}]
