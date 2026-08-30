"""Entry-point detection (spec section 22).

Three sources, all deterministic:

1. ``if __name__ == "__main__":`` guards in module bodies (found by the extractor).
2. Declared console scripts: ``[project.scripts]`` and
   ``[project.entry-points."console_scripts"]`` in pyproject.toml, ``[options.entry_points]``
   in setup.cfg, and a best-effort regex over ``setup.py``.
3. Framework mains: a module that calls ``uvicorn.run(...)`` / ``<app>.run(...)`` or
   assigns ``FastAPI()`` / ``Flask(...)`` at module level (found by the extractor).
"""

from __future__ import annotations

import configparser
import re
import tomllib
from pathlib import Path

_SETUP_PY_ENTRY = re.compile(
    r"""console_scripts['"]?\s*[:=]\s*\[(?P<body>.*?)\]""", re.DOTALL
)
_ENTRY_LINE = re.compile(r"""['"]\s*(?P<name>[\w.-]+)\s*=\s*(?P<target>[\w.]+:[\w.]+)\s*['"]""")


def _split_target(target: str) -> tuple[str, str | None]:
    if ":" in target:
        mod, func = target.split(":", 1)
        return mod.strip(), func.strip()
    return target.strip(), None


def declared_console_scripts(repo_dir: Path) -> list[dict]:
    """Return [{name, module, function, source}] for every declared console script."""
    found: list[dict] = []

    pp = repo_dir / "pyproject.toml"
    if pp.is_file():
        try:
            data = tomllib.loads(pp.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            data = {}
        project = data.get("project", {})
        scripts = dict(project.get("scripts", {}))
        ep = project.get("entry-points", {})
        if isinstance(ep, dict):
            scripts.update(ep.get("console_scripts", {}) or {})
        for name, target in scripts.items():
            mod, func = _split_target(str(target))
            found.append(
                {"name": name, "module": mod, "function": func, "source": "pyproject.toml"}
            )

    cfg = repo_dir / "setup.cfg"
    if cfg.is_file():
        parser = configparser.ConfigParser()
        try:
            parser.read(cfg, encoding="utf-8")
            raw = parser.get("options.entry_points", "console_scripts", fallback="")
        except (configparser.Error, OSError):
            raw = ""
        for line in raw.splitlines():
            line = line.strip()
            if "=" in line:
                name, target = line.split("=", 1)
                mod, func = _split_target(target)
                found.append(
                    {"name": name.strip(), "module": mod, "function": func, "source": "setup.cfg"}
                )

    sp = repo_dir / "setup.py"
    if sp.is_file():
        try:
            text = sp.read_text(encoding="utf-8")
        except OSError:
            text = ""
        block = _SETUP_PY_ENTRY.search(text)
        if block:
            for m in _ENTRY_LINE.finditer(block.group("body")):
                mod, func = _split_target(m.group("target"))
                found.append(
                    {"name": m.group("name"), "module": mod, "function": func, "source": "setup.py"}
                )

    # de-duplicate by (name, module, function)
    seen: set[tuple] = set()
    unique: list[dict] = []
    for item in found:
        key = (item["name"], item["module"], item["function"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
