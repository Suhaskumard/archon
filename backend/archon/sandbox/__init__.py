"""Secure execution sandbox (spec sections 12, 36).

All repository code is UNTRUSTED. ``Sandbox`` is the seam every execution engine runs
through; ``DockerSandbox`` is the only driver today, but the ABC keeps room for a
future non-Docker one.
"""

from __future__ import annotations

from archon.config import get_settings
from archon.sandbox.base import Sandbox


def get_sandbox() -> Sandbox:
    from archon.sandbox.docker_sandbox import DockerSandbox

    return DockerSandbox(get_settings().sandbox.image)

