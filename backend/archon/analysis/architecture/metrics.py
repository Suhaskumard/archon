"""Coupling & centrality metrics on the module dependency graph (spec section 23).

Per module (Martin's package metrics + graph centrality):

    fan_in                  number of modules that depend on this one
    fan_out                 number of modules this one depends on
    instability             fan_out / (fan_in + fan_out)   in [0, 1]
    degree_centrality       NetworkX degree centrality
    betweenness_centrality  NetworkX betweenness centrality
    pagerank                NetworkX PageRank
    in_cycle / scc_size     strongly-connected-component membership
    dependents              module qns that depend on this one (predecessors)
    dependencies            module qns this one depends on (successors)
"""

from __future__ import annotations

import networkx as nx

METRICS_VERSION = "arch_metrics.v1"


def _pagerank(g: nx.DiGraph, alpha: float = 0.85, max_iter: int = 100, tol: float = 1e-9) -> dict:
    """Pure-Python PageRank (NetworkX's needs numpy; we keep dependencies minimal)."""
    n = g.number_of_nodes()
    if n == 0:
        return {}
    x = dict.fromkeys(g, 1.0 / n)
    dangling = [v for v in g if g.out_degree(v) == 0]
    for _ in range(max_iter):
        xlast = x
        x = dict.fromkeys(xlast, 0.0)
        danglesum = alpha * sum(xlast[v] for v in dangling)
        for v in xlast:
            deg = g.out_degree(v)
            if not deg:
                continue
            share = alpha * xlast[v] / deg
            for _, w in g.out_edges(v):
                x[w] += share
        for v in x:
            x[v] += danglesum / n + (1.0 - alpha) / n
        if sum(abs(x[v] - xlast[v]) for v in x) < tol * n:
            break
    return x


def module_metrics(mg: nx.DiGraph) -> dict[str, dict]:
    n = mg.number_of_nodes()
    if n == 0:
        return {}

    betweenness = nx.betweenness_centrality(mg) if n > 2 else dict.fromkeys(mg, 0.0)
    degree = nx.degree_centrality(mg) if n > 1 else dict.fromkeys(mg, 0.0)
    pagerank = _pagerank(mg) if mg.number_of_edges() else dict.fromkeys(mg, 1.0 / n)

    scc_of: dict[str, frozenset] = {}
    for scc in nx.strongly_connected_components(mg):
        fs = frozenset(scc)
        for node in fs:
            scc_of[node] = fs

    out: dict[str, dict] = {}
    for node in mg.nodes:
        fan_in = mg.in_degree(node)
        fan_out = mg.out_degree(node)
        scc = scc_of.get(node, frozenset({node}))
        out[node] = {
            "fan_in": fan_in,
            "fan_out": fan_out,
            "instability": round(fan_out / (fan_in + fan_out), 4) if (fan_in + fan_out) else 0.0,
            "degree_centrality": round(degree.get(node, 0.0), 4),
            "betweenness_centrality": round(betweenness.get(node, 0.0), 4),
            "pagerank": round(pagerank.get(node, 0.0), 4),
            "in_cycle": len(scc) > 1 or mg.has_edge(node, node),
            "scc_size": len(scc),
            "dependents": sorted(mg.nodes[p]["qualified_name"] for p in mg.predecessors(node)),
            "dependencies": sorted(mg.nodes[s]["qualified_name"] for s in mg.successors(node)),
        }
    return out
