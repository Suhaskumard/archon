"""Deterministic module role inference (spec section 23).

``roles.v1`` - an explicit, ordered decision procedure. Signals: the ``is_test`` /
``is_entrypoint`` flags from Phase 2, the module's name + path tokens, the top-level roots
of everything it imports, the decorators on its functions/methods, and the mix of classes
vs functions it defines.

Precedence (first match wins):

    test        is_test
    config      name/path token in CONFIG_TOKENS
    entrypoint  is_entrypoint, or "__main__" token
    api         imports a web framework, OR path token in API_PATH_TOKENS,
                OR a function carries a route-style decorator
    cli         imports a CLI library and defines something, OR name/path token in CLI_TOKENS
    model       name/path token in MODEL_TOKENS,
                OR imports an ORM/schema library and defines >=1 class,
                OR the module is "class-heavy" (>=1 class and >=80% of top-level defs are classes)
    io          imports an I/O library, OR name/path token in IO_TOKENS
    util        name/path token in UTIL_TOKENS
    domain      defines something or participates in the internal dependency graph
    unknown     otherwise (e.g. an empty package __init__)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

ROLE_VERSION = "roles.v1"

WEB_FRAMEWORKS = {
    "fastapi", "flask", "django", "starlette", "aiohttp", "sanic", "bottle", "tornado",
    "falcon", "quart", "litestar",
}
API_PATH_TOKENS = {
    "api", "routes", "route", "endpoints", "endpoint", "views", "handlers", "resources",
    "controllers",
}
ROUTE_DECORATOR_HINTS = ("route", "get", "post", "put", "patch", "delete", "websocket")
CLI_LIBS = {"click", "typer", "argparse", "fire", "docopt"}
CLI_TOKENS = {"cli", "cmd", "command", "commands", "console"}
MODEL_LIBS = {
    "sqlalchemy", "pydantic", "attr", "attrs", "marshmallow", "peewee", "tortoise",
    "sqlmodel", "mongoengine",
}
MODEL_TOKENS = {"model", "models", "schema", "schemas", "entity", "entities", "dto"}
IO_LIBS = {
    "httpx", "requests", "urllib3", "boto3", "botocore", "psycopg", "psycopg2", "pymysql",
    "sqlite3", "redis", "pymongo", "kafka", "pika", "socket", "smtplib", "ftplib",
    "paramiko", "elasticsearch", "aioredis", "asyncpg",
}
IO_TOKENS = {
    "db", "database", "store", "storage", "repository", "repositories", "client", "clients",
    "gateway", "gateways", "adapter", "adapters", "io", "persistence", "dao", "cache",
    "queue", "broker",
}
CONFIG_TOKENS = {"config", "configuration", "settings", "conf", "constants"}
UTIL_TOKENS = {
    "util", "utils", "helper", "helpers", "common", "commons", "lib", "libs", "tools",
    "misc", "shared",
}

ALL_ROLES = (
    "test", "config", "entrypoint", "api", "cli", "model", "io", "util", "domain", "unknown",
)


@dataclass
class RoleContext:
    qualified_name: str
    name: str
    path: str
    is_test: bool = False
    is_entrypoint: bool = False
    class_count: int = 0
    function_count: int = 0
    import_roots: set[str] = field(default_factory=set)
    decorator_names: list[str] = field(default_factory=list)
    in_internal_graph: bool = False

    @property
    def has_defs(self) -> bool:
        return (self.class_count + self.function_count) > 0

    def tokens(self) -> set[str]:
        toks = {p for p in self.qualified_name.lower().replace("-", "_").split(".") if p}
        stem = PurePosixPath(self.path.lower())
        toks |= {p for p in stem.with_suffix("").parts if p}
        toks.add(self.name.lower().removesuffix(".py"))
        return toks


def infer_role(ctx: RoleContext) -> str:
    if ctx.is_test:
        return "test"

    toks = ctx.tokens()
    roots = ctx.import_roots
    decos = " ".join(ctx.decorator_names).lower()

    if toks & CONFIG_TOKENS:
        return "config"
    if ctx.is_entrypoint or "__main__" in toks:
        return "entrypoint"
    if (
        (roots & WEB_FRAMEWORKS)
        or (toks & API_PATH_TOKENS)
        or any(f".{h}" in decos or decos.startswith(h) for h in ROUTE_DECORATOR_HINTS)
    ):
        return "api"
    if (roots & CLI_LIBS and ctx.has_defs) or (toks & CLI_TOKENS):
        return "cli"

    total_defs = ctx.class_count + ctx.function_count
    class_heavy = ctx.class_count >= 1 and (
        ctx.function_count == 0 or ctx.class_count / max(total_defs, 1) >= 0.8
    )
    if (toks & MODEL_TOKENS) or (roots & MODEL_LIBS and ctx.class_count >= 1) or class_heavy:
        return "model"
    if (roots & IO_LIBS) or (toks & IO_TOKENS):
        return "io"
    if toks & UTIL_TOKENS:
        return "util"
    if ctx.has_defs or ctx.in_internal_graph:
        return "domain"
    return "unknown"


# --- layering rules -------------------------------------------------------------------
# A forbidden edge is a lower-level module depending on a higher-level one, or any
# non-test module depending on a test module. Conservative on purpose: model->domain and
# io->domain are allowed (data classes routinely use domain helpers).

_FORBIDDEN_TARGETS = {"api", "cli", "entrypoint"}
_LOWER_SOURCES = {"domain", "model", "io", "util", "config"}


def layering_violation(src_role: str | None, dst_role: str | None) -> str | None:
    if not src_role or not dst_role:
        return None
    if dst_role == "test" and src_role != "test":
        return "non-test module depends on a test module"
    if dst_role in _FORBIDDEN_TARGETS and src_role in _LOWER_SOURCES:
        return f"{src_role} module depends on {dst_role} module (wrong direction)"
    return None
