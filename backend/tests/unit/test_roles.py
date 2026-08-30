"""roles.v1 - one assertion per precedence branch (spec section 23)."""

import pytest

from archon.analysis.architecture.roles import RoleContext, infer_role, layering_violation


def ctx(**kw) -> RoleContext:
    base = dict(qualified_name="pkg.mod", name="mod", path="pkg/mod.py")
    base.update(kw)
    return RoleContext(**base)


@pytest.mark.parametrize(
    "context,expected",
    [
        (ctx(is_test=True, function_count=1), "test"),
        (ctx(qualified_name="pkg.settings", name="settings", path="pkg/settings.py",
             function_count=1), "config"),
        (ctx(is_entrypoint=True, function_count=1), "entrypoint"),
        (ctx(qualified_name="pkg.__main__", name="__main__", path="pkg/__main__.py"),
         "entrypoint"),
        (ctx(import_roots={"fastapi"}, function_count=2), "api"),
        (ctx(path="pkg/api/users.py", qualified_name="pkg.api.users", name="users",
             function_count=2), "api"),
        (ctx(decorator_names=["router.get"], function_count=1), "api"),
        (ctx(import_roots={"typer"}, function_count=1,
             qualified_name="pkg.console", name="console", path="pkg/console.py"), "cli"),
        (ctx(qualified_name="pkg.models", name="models", path="pkg/models.py",
             class_count=3, function_count=1), "model"),
        (ctx(class_count=2, function_count=0), "model"),                       # class-heavy
        (ctx(import_roots={"pydantic"}, class_count=1, function_count=1,
             qualified_name="pkg.thing", name="thing"), "model"),
        (ctx(import_roots={"httpx"}, function_count=2), "io"),
        (ctx(qualified_name="pkg.db.client", name="client", path="pkg/db/client.py",
             function_count=1), "io"),
        (ctx(qualified_name="pkg.utils", name="utils", path="pkg/utils.py",
             function_count=3), "util"),
        (ctx(function_count=2), "domain"),
        (ctx(in_internal_graph=True), "domain"),
        (ctx(), "unknown"),
    ],
)
def test_infer_role(context, expected):
    assert infer_role(context) == expected


def test_precedence_test_beats_everything():
    assert infer_role(ctx(is_test=True, import_roots={"fastapi"}, class_count=5)) == "test"


def test_layering_violation_rules():
    assert layering_violation("domain", "api") is not None
    assert layering_violation("util", "cli") is not None
    assert layering_violation("domain", "test") is not None
    # allowed directions
    assert layering_violation("api", "domain") is None
    assert layering_violation("model", "domain") is None      # data classes may use domain
    assert layering_violation("test", "domain") is None
    assert layering_violation(None, "api") is None
