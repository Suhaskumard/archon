"""Build the Phase 7 sandbox-containment fixture (spec sections 12, 36).

Not a git repo - just a small pytest-discoverable directory. Each test function
attempts exactly one bad behaviour; every one is safe-by-construction because the
sandbox's own controls stop it fast (see docker_sandbox.py's threat-model flags):

* ``test_network_call``  - network=none means there is no interface at all, so this
  fails instantly with "Network is unreachable" - no real traffic ever leaves the host.
* ``test_fork_bomb``     - bounded loop; --pids-limit caps it at the kernel level
  regardless of the loop's own bound, so it always contains fast.
* ``test_secret_read``   - checks the sandbox's env is empty of ARCHON secrets, then
  tries to read a root-only file - fails with PermissionError (non-root user).
* ``test_fs_escape``     - writes outside /work - fails with "Read-only file system".
"""

from __future__ import annotations

from pathlib import Path

_TEST_MALICIOUS_PY = '''\
import os
import socket
import time


def test_network_call():
    with socket.create_connection(("8.8.8.8", 53), timeout=2):
        pass


def test_fork_bomb():
    n = 0
    try:
        while n < 10000:
            pid = os.fork()
            if pid == 0:
                time.sleep(5)
                os._exit(0)
            n += 1
    except OSError:
        pass
    assert False, f"forked {n} process(es) before containment stopped it"


def test_secret_read():
    assert "ARCHON_GITHUB_TOKEN" not in os.environ
    with open("/etc/shadow"):
        pass


def test_fs_escape():
    with open("/etc/archon_escape_test", "w") as f:
        f.write("pwned")
'''


def build_malicious_repo(dest: Path) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "test_malicious.py").write_text(_TEST_MALICIOUS_PY, encoding="utf-8")
    return dest


if __name__ == "__main__":  # pragma: no cover
    import sys

    out = build_malicious_repo(Path(sys.argv[1] if len(sys.argv) > 1 else "./_malicious_fixture"))
    print(f"built malicious fixture at {out}")
