"""GitHub push-payload parsing + changed-component resolution (Phase 19)."""

from __future__ import annotations

from archon.analysis.incremental.scope import resolve_changed_components
from archon.api.routers.webhooks import _changed_paths, _is_delete, _resolve_repo
from archon.db.base import session_scope
from archon.db.models import Component, Repository, RepositorySnapshot
from archon.domain.enums import ComponentKind, ProviderKind, SupportLevel


def test_changed_paths_unions_dedups_sorts():
    payload = {
        "commits": [
            {"added": ["a.py"], "modified": ["b.py"], "removed": []},
            {"added": [], "modified": ["b.py", "c.py"], "removed": ["d.py"]},
        ]
    }
    assert _changed_paths(payload) == ["a.py", "b.py", "c.py", "d.py"]


def test_changed_paths_falls_back_to_head_commit():
    payload = {"commits": [], "head_commit": {"modified": ["only.py"], "added": [], "removed": []}}
    assert _changed_paths(payload) == ["only.py"]


def test_changed_paths_empty():
    assert _changed_paths({}) == []


def test_is_delete_detects_branch_deletion():
    assert _is_delete({"deleted": True}) is True
    assert _is_delete({"after": "0" * 40}) is True
    assert _is_delete({"after": "abc123", "deleted": False}) is False


def test_resolve_repo_matches_html_url_and_full_name():
    with session_scope() as session:
        repo = Repository(
            provider=ProviderKind.GITHUB, url="https://github.com/acme/widgets",
            owner="acme", name="widgets",
        )
        session.add(repo)
        session.flush()

        assert _resolve_repo(session, {"html_url": "https://github.com/acme/widgets"}).id == repo.id
        assert _resolve_repo(session, {"full_name": "acme/widgets"}).id == repo.id
        assert _resolve_repo(session, {"html_url": "https://github.com/acme/other"}) is None
        assert _resolve_repo(session, {}) is None


def test_resolve_changed_components_scopes_to_paths():
    with session_scope() as session:
        repo = Repository(provider=ProviderKind.GITHUB, url="https://github.com/x/y", name="y")
        session.add(repo)
        session.flush()
        snap = RepositorySnapshot(
            repository_id=repo.id, commit_sha="c1", support_level=SupportLevel.SUPPORTED,
        )
        session.add(snap)
        session.flush()
        keep = Component(
            snapshot_id=snap.id, kind=ComponentKind.FUNCTION, name="f",
            qualified_name="pkg.mod.f", path="pkg/mod.py", start_line=1, end_line=5,
        )
        skip = Component(
            snapshot_id=snap.id, kind=ComponentKind.FUNCTION, name="g",
            qualified_name="pkg.other.g", path="pkg/other.py", start_line=1, end_line=5,
        )
        session.add_all([keep, skip])
        session.flush()

        got = resolve_changed_components(session, snap, ["./pkg/mod.py"])
        assert got == [keep.id]
        assert resolve_changed_components(session, snap, []) == []
        assert resolve_changed_components(session, snap, None) == []
