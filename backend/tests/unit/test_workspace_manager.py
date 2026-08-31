import pytest

from archon.core.errors import ArchonError, ErrorCode
from archon.workspace.manager import WorkspaceManager


def test_create_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHON_WORKSPACE_ROOT", str(tmp_path / "ws"))
    import archon.config as config

    config.reset_settings_cache()
    mgr = WorkspaceManager()
    ws = mgr.create()
    assert ws.path.exists()
    assert ws.path.parent == mgr.root
    mgr.cleanup(ws)
    assert not ws.path.exists()


def test_resolve_within_blocks_traversal():
    mgr = WorkspaceManager()
    ws = mgr.create()
    try:
        assert ws.resolve_within("repo/sub").name == "sub"
        with pytest.raises(ArchonError) as exc:
            ws.resolve_within("../../etc/passwd")
        assert exc.value.code is ErrorCode.PATH_TRAVERSAL
    finally:
        mgr.cleanup(ws)


def test_quota_enforced(monkeypatch):
    monkeypatch.setenv("ARCHON_WORKSPACE_QUOTA_BYTES", "0")
    import archon.config as config

    config.reset_settings_cache()
    mgr = WorkspaceManager()
    with pytest.raises(ArchonError) as exc:
        mgr.create()
    assert exc.value.code is ErrorCode.WORKSPACE_QUOTA_EXCEEDED


def test_scoped_cleans_up_on_exit():
    mgr = WorkspaceManager()
    with mgr.scoped() as ws:
        p = ws.path
        assert p.exists()
    assert not p.exists()


def test_clone_copies_repo_independently():
    mgr = WorkspaceManager()
    source = mgr.create("src")
    try:
        (source.resolve_within("repo")).mkdir(parents=True)
        (source.resolve_within("repo") / "a.py").write_text("x = 1\n", encoding="utf-8")

        clone = mgr.clone(source, "clone")
        try:
            assert (clone.resolve_within("repo") / "a.py").read_text(encoding="utf-8") == "x = 1\n"
            # independent: mutating the clone never touches the source
            (clone.resolve_within("repo") / "a.py").write_text("x = 2\n", encoding="utf-8")
            assert (source.resolve_within("repo") / "a.py").read_text(encoding="utf-8") == "x = 1\n"
        finally:
            mgr.cleanup(clone)
    finally:
        mgr.cleanup(source)
