import ast

import pytest

from archon.analysis.source.complexity import complexity_of_body, complexity_of_node


def _fn(src: str) -> ast.AST:
    return ast.parse(src).body[0]


@pytest.mark.parametrize(
    "src,expected",
    [
        ("def f():\n    return 1\n", 1),
        ("def f(x):\n    if x:\n        return 1\n    return 0\n", 2),
        ("def f(x):\n    if x:\n        pass\n    elif x == 2:\n        pass\n", 3),
        ("def f(xs):\n    for x in xs:\n        pass\n", 2),
        ("def f(x):\n    while x:\n        x -= 1\n", 2),
        ("def f(a, b):\n    return a and b or a\n", 3),  # one BoolOp(and) +1, one BoolOp(or) +1
        ("def f():\n    try:\n        pass\n    except ValueError:\n        pass\n    except KeyError:\n        pass\n", 3),
        ("def f(x):\n    return 1 if x else 0\n", 2),  # ternary
        ("def f(xs):\n    return [x for x in xs if x > 0]\n", 3),  # comp for +1, comp if +1
        ("def f(x):\n    assert x\n", 2),
        ("def f(x):\n    match x:\n        case 1:\n            pass\n        case _:\n            pass\n", 3),
    ],
)
def test_function_complexity(src, expected):
    assert complexity_of_node(_fn(src)) == expected


def test_nested_function_not_counted_in_parent():
    src = (
        "def outer(x):\n"
        "    if x:\n"
        "        pass\n"
        "    def inner(y):\n"
        "        if y:\n"
        "            if y > 1:\n"
        "                return 1\n"
        "        return 0\n"
        "    return inner\n"
    )
    outer = _fn(src)
    assert complexity_of_node(outer) == 2  # only outer's own `if`
    inner = outer.body[1]
    assert complexity_of_node(inner) == 3


def test_module_level_complexity():
    src = "x = 1\nif x:\n    x = 2\nfor i in range(3):\n    x += i\n"
    assert complexity_of_body(ast.parse(src).body) == 3
