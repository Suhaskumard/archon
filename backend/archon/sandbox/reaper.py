"""Container reaper for orphaned sandbox containers (spec sections 12, 36).

Mirrors ``workspace.manager.WorkspaceManager.reap_orphans`` - remove anything a crashed
worker left behind, identified by the ``archon.managed=true`` label every sandbox
container carries.
"""

from __future__ import annotations

import subprocess

from archon.core.logging import get_logger

log = get_logger("archon.sandbox")


def reap_orphan_containers() -> int:
    proc = subprocess.run(
        ["docker", "ps", "-a", "--filter", "label=archon.managed=true", "--format", "{{.ID}}"],
        capture_output=True, text=True, shell=False, check=False,
    )
    if proc.returncode != 0:
        log.warning(
            "sandbox reaper could not list containers (docker unavailable?)",
            extra={"extra_fields": {"stderr": proc.stderr.strip()[:500]}},
        )
        return 0
    ids = [i for i in proc.stdout.splitlines() if i.strip()]
    removed = 0
    for cid in ids:
        r = subprocess.run(["docker", "rm", "-f", cid], capture_output=True, shell=False, check=False)
        if r.returncode == 0:
            removed += 1
    if removed:
        log.info("reaped orphan sandbox containers", extra={"extra_fields": {"count": removed}})
    return removed
