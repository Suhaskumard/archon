"""Module-graph metrics + cycle detection on hand-built graphs (spec section 23)."""

import networkx as nx

from archon.analysis.architecture.metrics import module_metrics
from archon.analysis.graph.derive import find_cycles


def _mg(edges, nodes=None):
    g = nx.DiGraph()
    for n in nodes or []:
        g.add_node(n, qualified_name=n)
    for u, v in edges:
        g.add_node(u, qualified_name=u)
        g.add_node(v, qualified_name=v)
        g.add_edge(u, v, weight=1, kinds={"IMPORTS"})
    return g


def test_fan_in_out_and_instability():
    #  a -> b -> c ,  d -> b
    g = _mg([("a", "b"), ("b", "c"), ("d", "b")])
    m = module_metrics(g)
    assert m["b"]["fan_in"] == 2 and m["b"]["fan_out"] == 1
    assert m["b"]["instability"] == round(1 / 3, 4)
    assert m["c"]["fan_out"] == 0 and m["c"]["instability"] == 0.0
    assert m["a"]["instability"] == 1.0  # only outgoing
    assert m["b"]["dependents"] == ["a", "d"]
    assert m["b"]["dependencies"] == ["c"]


def test_betweenness_identifies_the_bridge():
    g = _mg([("a", "b"), ("b", "c"), ("x", "b"), ("b", "y")])
    m = module_metrics(g)
    assert m["b"]["betweenness_centrality"] == max(
        v["betweenness_centrality"] for v in m.values()
    )
    assert m["b"]["betweenness_centrality"] > 0


def test_scc_and_in_cycle():
    g = _mg([("a", "b"), ("b", "a"), ("b", "c")])
    m = module_metrics(g)
    assert m["a"]["in_cycle"] and m["b"]["in_cycle"]
    assert m["a"]["scc_size"] == 2
    assert not m["c"]["in_cycle"]


def test_find_cycles():
    assert find_cycles(_mg([("a", "b"), ("b", "c")])) == []          # DAG
    two = find_cycles(_mg([("a", "b"), ("b", "a")]))
    assert len(two) == 1 and set(two[0]) == {"a", "b"}
    three = find_cycles(_mg([("a", "b"), ("b", "c"), ("c", "a")]))
    assert len(three) == 1 and set(three[0]) == {"a", "b", "c"}


def test_find_cycles_self_loop():
    g = _mg([("a", "b")])
    g.add_edge("a", "a", weight=1, kinds={"IMPORTS"})
    cyc = find_cycles(g)
    assert ["a"] in cyc
