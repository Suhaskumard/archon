import ast

from archon.healing.generation import _find_divisor
from archon.testing.characterization import _find_function_node


def test_find_divisor_locates_binop_div_and_column():
    source = "def divide(a, b):\n    return a / b\n"
    node = _find_function_node(source, "divide", 1)
    divisor, return_expr, col_offset = _find_divisor(node, source)
    assert divisor == "b"
    assert return_expr == "return a / b"
    assert col_offset == 4  # indented one level inside the function


def test_find_divisor_returns_none_when_no_division():
    source = "def add(a, b):\n    return a + b\n"
    node = _find_function_node(source, "add", 1)
    divisor, return_expr, col_offset = _find_divisor(node, source)
    assert divisor is None
    assert return_expr is None


def test_find_divisor_ignores_non_name_divisor():
    source = "def half(a):\n    return a / 2\n"
    node = _find_function_node(source, "half", 1)
    divisor, return_expr, col_offset = _find_divisor(node, source)
    assert divisor is None  # divisor is a constant, not a parameter name


def test_guard_reconstruction_is_syntactically_valid():
    """Regression test: an earlier version produced mis-indented guards that failed
    to parse once spliced back into the file (indent must come from the file's real
    column offset, not from the whitespace-free ``ast.get_source_segment`` text)."""
    source = "def divide(a, b):\n    return a / b\n"
    node = _find_function_node(source, "divide", 1)
    divisor, return_expr, col_offset = _find_divisor(node, source)
    indent = " " * col_offset
    new_snippet = f"if {divisor} == 0:\n{indent}    return None\n{indent}{return_expr}"
    new_source = source.replace(return_expr, new_snippet, 1)
    ast.parse(new_source)  # raises SyntaxError if mis-indented
