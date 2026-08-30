"""build_module_graph collapses component edges to module edges (spec section 23)."""

from __future__ import annotations

from archon.analysis.graph.builder import build_module_graph, module_id_by_qn
from archon.db.base import session_scope
from archon.db.models import Component, Dependency, Repository, RepositorySnapshot
from archon.domain.enums import ComponentKind, DependencyKind, ProviderKind, SupportLevel


def _seed():
    """m_a.f -> m_b.g (CALLS) ; m_a IMPORTS m_b ; m_b IMPORTS m_c ; intra-module edge ignored."""
    with session_scope() as s:
        repo = Repository(provider=ProviderKind.LOCAL, url="/x", name="x")
        s.add(repo)
        s.flush()
        snap = RepositorySnapshot(
            repository_id=repo.id, commit_sha="0" * 40, support_level=SupportLevel.SUPPORTED
        )
        s.add(snap)
        s.flush()

        def comp(kind, qn, path, parent=None):
            c = Component(
                snapshot_id=snap.id, kind=kind, name=qn.split(".")[-1],
                qualified_name=qn, path=path, parent_id=parent,
            )
            s.add(c)
            s.flush()
            return c

        ma = comp(ComponentKind.MODULE, "m_a", "m_a.py")
        mb = comp(ComponentKind.MODULE, "m_b", "m_b.py")
        mc = comp(ComponentKind.MODULE, "m_c", "m_c.py")
        fa = comp(ComponentKind.FUNCTION, "m_a.f", "m_a.py", parent=ma.id)
        fa2 = comp(ComponentKind.FUNCTION, "m_a.f2", "m_a.py", parent=ma.id)
        gb = comp(ComponentKind.FUNCTION, "m_b.g", "m_b.py", parent=mb.id)

        def edge(kind, src, dst):
            s.add(Dependency(
                snapshot_id=snap.id, kind=kind, src_component_id=src, dst_component_id=dst,
                target_name="t", resolved=True,
            ))

        edge(DependencyKind.IMPORTS, ma.id, mb.id)
        edge(DependencyKind.IMPORTS, mb.id, mc.id)
        edge(DependencyKind.CALLS, fa.id, gb.id)          # m_a -> m_b (second contribution)
        edge(DependencyKind.CALLS, fa.id, fa2.id)         # intra-module -> ignored
        edge(DependencyKind.CONTAINS, ma.id, fa.id)       # never a module edge
        return snap.id


def test_module_graph_collapse():
    sid = _seed()
    with session_scope() as s:
        mg = build_module_graph(s, sid)
        idx = module_id_by_qn(mg)
        assert set(idx) == {"m_a", "m_b", "m_c"}

        assert mg.has_edge(idx["m_a"], idx["m_b"])
        assert mg.has_edge(idx["m_b"], idx["m_c"])
        assert not mg.has_edge(idx["m_a"], idx["m_c"])     # no transitive edge
        assert not mg.has_edge(idx["m_a"], idx["m_a"])     # intra-module ignored

        ab = mg.edges[idx["m_a"], idx["m_b"]]
        assert ab["weight"] == 2                            # IMPORTS + CALLS
        assert ab["kinds"] == {"IMPORTS", "CALLS"}
