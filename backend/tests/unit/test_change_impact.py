import networkx as nx

from archon.analysis.scoring.change_impact import direct_and_indirect_dependents


def _diamond_plus_chain() -> nx.DiGraph:
    """a -> b -> d, a -> c -> d, d -> e (edges point dependent -> dependency, so a/b/c
    all (transitively) depend on d; e is upstream of d, not a dependent)."""
    g = nx.DiGraph()
    g.add_edges_from([("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("d", "e")])
    return g


def test_direct_dependents_are_predecessors():
    g = _diamond_plus_chain()
    direct, _indirect = direct_and_indirect_dependents(g, "d")
    assert direct == {"b", "c"}


def test_indirect_dependents_are_ancestors_minus_direct_minus_self():
    g = _diamond_plus_chain()
    direct, indirect = direct_and_indirect_dependents(g, "d")
    assert indirect == {"a"}
    assert "d" not in indirect
    assert not (direct & indirect)


def test_node_with_no_dependents_is_empty():
    g = _diamond_plus_chain()
    direct, indirect = direct_and_indirect_dependents(g, "a")
    assert direct == set()
    assert indirect == set()


def test_upstream_node_is_not_a_dependent():
    g = _diamond_plus_chain()
    direct, indirect = direct_and_indirect_dependents(g, "d")
    assert "e" not in direct
    assert "e" not in indirect
