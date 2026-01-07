"""Filter components by Core Influence Score (CIS).

This script consumes a dependency-graph JSON produced by
`dependency_analyzer.ast_parser.DependencyParser.save_dependency_graph()`.

Input JSON schema (dict):
  {
    "component.id": {
      "id": "...",
      "component_type": "class"|"function"|"method",
      "file_path": "...",
      "relative_path": "...",
      "depends_on": ["other.component", ...],
      ...
    },
    ...
  }

We rebuild the *repo-internal* dependency graph:
- Nodes are component IDs from the input JSON keys.
- Directed edges follow the natural dependency direction:
    A -> B  iff  component A depends_on component B and B exists in the repo.

Metrics:
- In-degree / Out-degree
- Betweenness centrality: approximated via sampling Brandes (unweighted, directed)
- PageRank: power iteration on the same directed graph

Score:
  score = alpha * norm(in_degree)
        + beta  * norm(out_degree)
        + gamma * norm(betweenness)
        +        norm(pagerank)

Then we keep the top P% components by score.

Design goals:
- No new third-party dependencies (pure Python).
- Fast on large repos: betweenness defaults to sampling.

Usage:
  python -m dependency_analyzer.filter_components_by_cis \
      --input data/parsed_downloaded_repos/raw_test_repo_dependency_graph.json \
      --output /tmp/filtered_components.json \
      --top-percent 20 \
      --alpha 1.0 --beta 1.0 --gamma 1.0

"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .ast_parser import load_dependency_graph
from .topo_sort import build_graph_from_components


@dataclass(frozen=True)
class Metrics:
    in_degree: int
    out_degree: int
    betweenness: float
    pagerank: float
    score: float


def _min_max_normalize(values: Mapping[str, float]) -> Dict[str, float]:
    if not values:
        return {}
    min_v = min(values.values())
    max_v = max(values.values())
    if math.isclose(min_v, max_v):
        return {k: 0.0 for k in values}
    span = max_v - min_v
    return {k: (v - min_v) / span for k, v in values.items()}


def build_in_out_edges_from_components(
    components: Mapping[str, object],
) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """Build (out_edges, in_edges) from repo components.

    This intentionally reuses dependency_analyzer.topo_sort.build_graph_from_components
    to keep graph semantics consistent across the codebase.
    """
    graph = build_graph_from_components(components)  # A -> deps
    nodes = set(components.keys())

    out_edges: Dict[str, Set[str]] = {node: set(graph.get(node, set())) for node in nodes}
    in_edges: Dict[str, Set[str]] = {node: set() for node in nodes}
    for src, deps in out_edges.items():
        for dst in deps:
            if dst in in_edges:
                in_edges[dst].add(src)

    return out_edges, in_edges


def _build_index_graph(out_edges: Mapping[str, Set[str]]) -> Tuple[List[str], List[List[int]]]:
    """Convert string-keyed adjacency sets into index-based adjacency lists for speed."""
    nodes = list(out_edges.keys())
    idx = {n: i for i, n in enumerate(nodes)}
    adjacency: List[List[int]] = [[] for _ in range(len(nodes))]
    for src, dsts in out_edges.items():
        u = idx[src]
        adjacency[u] = [idx[d] for d in dsts if d in idx]
    return nodes, adjacency


def compute_pagerank(
    out_edges: Mapping[str, Set[str]],
    damping: float = 0.85,
    max_iter: int = 50,
    tol: float = 1e-8,
) -> Dict[str, float]:
    """Simple PageRank on directed graph (power iteration).

    Important: edges are A -> dependency. This makes dependencies accumulate rank.
    """
    nodes = list(out_edges.keys())
    n = len(nodes)
    if n == 0:
        return {}

    node_index = {node: i for i, node in enumerate(nodes)}

    # Precompute incoming edges for speed
    in_edges: Dict[str, List[str]] = {node: [] for node in nodes}
    out_degree = {node: len(out_edges[node]) for node in nodes}
    for src, dsts in out_edges.items():
        for dst in dsts:
            in_edges[dst].append(src)

    rank = {node: 1.0 / n for node in nodes}

    for _ in range(max_iter):
        prev = rank
        rank = {node: (1.0 - damping) / n for node in nodes}

        # Dangling mass: nodes with no out edges distribute uniformly
        dangling_mass = sum(prev[node] for node in nodes if out_degree[node] == 0)
        dangling_share = damping * dangling_mass / n
        if dangling_share:
            for node in nodes:
                rank[node] += dangling_share

        for node in nodes:
            s = 0.0
            for src in in_edges[node]:
                deg = out_degree[src]
                if deg > 0:
                    s += prev[src] / deg
            rank[node] += damping * s

        # Check convergence (L1)
        diff = sum(abs(rank[node] - prev[node]) for node in nodes)
        if diff < tol:
            break

    return rank


def compute_betweenness(
    out_edges: Mapping[str, Set[str]],
    samples: int,
    seed: int = 0,
) -> Dict[str, float]:
    """Betweenness centrality (Brandes) for unweighted directed graphs.

    Sampling behavior:
    - samples == 0: exact (use all nodes as sources)
    - samples  > 0: approximate (sample that many sources)
    - samples  < 0: disabled (all zeros)

    Complexity:
    - Exact:  O(V * (V+E))
    - Sample: O(samples * (V+E))

    Implementation notes:
    - Uses index-based adjacency and reuses work buffers to reduce allocations.
    """
    nodes, adjacency = _build_index_graph(out_edges)
    n = len(nodes)
    if n == 0:
        return {}

    if samples < 0:
        return {node: 0.0 for node in nodes}

    if samples == 0 or samples >= n:
        sources = list(range(n))
        scale = 1.0
    else:
        rng = random.Random(seed)
        sources = rng.sample(range(n), k=samples)
        scale = float(n) / float(len(sources))

    cb = [0.0] * n

    # Reused buffers
    q: deque[int] = deque()
    stack: List[int] = []
    pred: List[List[int]] = [[] for _ in range(n)]
    sigma = [0.0] * n
    dist = [-1] * n
    delta = [0.0] * n
    touched: List[int] = []

    for s in sources:
        q.clear()
        stack.clear()
        touched.clear()

        q.append(s)
        dist[s] = 0
        sigma[s] = 1.0
        touched.append(s)

        while q:
            v = q.popleft()
            stack.append(v)
            dv = dist[v]
            for w in adjacency[v]:
                if dist[w] < 0:
                    dist[w] = dv + 1
                    q.append(w)
                    touched.append(w)
                if dist[w] == dv + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)

        while stack:
            w = stack.pop()
            for v in pred[w]:
                if sigma[w] != 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                cb[w] += delta[w]

        for v in touched:
            dist[v] = -1
            sigma[v] = 0.0
            delta[v] = 0.0
            pred[v].clear()

    cb = [x * scale for x in cb]
    return {nodes[i]: cb[i] for i in range(n)}


def compute_metrics(
    out_edges: Mapping[str, Set[str]],
    in_edges: Mapping[str, Set[str]],
    *,
    alpha: float,
    beta: float,
    gamma: float,
    betweenness_samples: int,
    betweenness_seed: int,
    pagerank_damping: float,
    pagerank_iters: int,
) -> Dict[str, Metrics]:
    nodes = list(out_edges.keys())

    in_deg = {n: float(len(in_edges[n])) for n in nodes}
    out_deg = {n: float(len(out_edges[n])) for n in nodes}

    pr = compute_pagerank(out_edges, damping=pagerank_damping, max_iter=pagerank_iters)
    bc = compute_betweenness(out_edges, samples=betweenness_samples, seed=betweenness_seed)

    in_n = _min_max_normalize(in_deg)
    out_n = _min_max_normalize(out_deg)
    bc_n = _min_max_normalize(bc)
    pr_n = _min_max_normalize(pr)

    metrics: Dict[str, Metrics] = {}
    for node in nodes:
        score = alpha * in_n.get(node, 0.0) + beta * out_n.get(node, 0.0) + gamma * bc_n.get(node, 0.0) + pr_n.get(node, 0.0)
        metrics[node] = Metrics(
            in_degree=int(in_deg[node]),
            out_degree=int(out_deg[node]),
            betweenness=float(bc.get(node, 0.0)),
            pagerank=float(pr.get(node, 0.0)),
            score=float(score),
        )

    return metrics


def select_top_percent(metrics: Mapping[str, Metrics], top_percent: float) -> List[str]:
    if top_percent <= 0:
        return []

    ids = list(metrics.keys())
    if top_percent >= 100:
        return sorted(ids)

    k = int(math.ceil(len(ids) * (top_percent / 100.0)))
    k = max(1, min(k, len(ids)))

    # Sort by score desc, tie-break by id for determinism
    ranked = sorted(ids, key=lambda cid: (-metrics[cid].score, cid))
    return ranked[:k]


def write_filtered_components(
    components: Mapping[str, object],
    selected_ids: Sequence[str],
    out_path: str,
) -> None:
    out: Dict[str, object] = {}
    for cid in selected_ids:
        comp = components.get(cid)
        if comp is None:
            continue
        if hasattr(comp, "to_dict"):
            out[cid] = comp.to_dict()
        else:
            out[cid] = comp
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Filter repo components by Core Influence Score (CIS) computed from a dependency graph JSON."
    )
    parser.add_argument("--input", required=True, help="Input dependency graph JSON (from DependencyParser.save_dependency_graph)")
    parser.add_argument("--output", required=True, help="Output JSON containing only selected components")
    parser.add_argument("--top-percent", type=float, default=100.0, help="Keep top P%% components by CIS score (0-100)")

    parser.add_argument("--alpha", type=float, default=1.0, help="Weight for normalized in-degree")
    parser.add_argument("--beta", type=float, default=1.0, help="Weight for normalized out-degree")
    parser.add_argument("--gamma", type=float, default=1.0, help="Weight for normalized betweenness")

    parser.add_argument(
        "--betweenness-samples",
        type=int,
        default=200,
        help=(
            "Betweenness sampling mode: 0=exact, >0=sampled (faster), <0=disabled. "
            "Default: 200"
        ),
    )
    parser.add_argument("--betweenness-seed", type=int, default=0, help="Random seed for betweenness sampling")

    parser.add_argument("--pagerank-damping", type=float, default=0.85, help="PageRank damping factor")
    parser.add_argument("--pagerank-iters", type=int, default=50, help="Max PageRank iterations")

    parser.add_argument(
        "--print-top-percent",
        type=float,
        default=0.0,
        help=(
            "Print top P%% components (ranked by CIS) to stdout (0 disables). "
            "For consistency with filtering, printing is capped at --top-percent."
        ),
    )

    # Backward compatibility: older flag printed a fixed count.
    parser.add_argument(
        "--print-top",
        type=int,
        default=None,
        help="(Deprecated) Print top K components (count). Prefer --print-top-percent.",
    )

    args = parser.parse_args(argv)

    components = load_dependency_graph(args.input)
    
    out_edges, in_edges = build_in_out_edges_from_components(components)

    n = len(out_edges)
    if n == 0:
        write_filtered_components(components, [], args.output)
        return 0

    # Make betweenness sampling adaptive to graph size
    bet_samples = args.betweenness_samples
    if bet_samples > 0:
        bet_samples = min(bet_samples, n)
    elif bet_samples == 0:
        # exact mode; keep 0
        pass

    metrics = compute_metrics(
        out_edges,
        in_edges,
        alpha=args.alpha,
        beta=args.beta,
        gamma=args.gamma,
        betweenness_samples=bet_samples,
        betweenness_seed=args.betweenness_seed,
        pagerank_damping=args.pagerank_damping,
        pagerank_iters=args.pagerank_iters,
    )

    selected = select_top_percent(metrics, args.top_percent)
    write_filtered_components(components, selected, args.output)

    # Printing (Scheme A): percent-based, with summary stats.
    if args.print_top is not None and args.print_top_percent and args.print_top_percent > 0:
        raise SystemExit("Use only one of --print-top or --print-top-percent")

    ranked = sorted(metrics.keys(), key=lambda cid: (-metrics[cid].score, cid))

    # Summary stats (printed together with top list)
    if (args.print_top_percent and args.print_top_percent > 0) or (args.print_top and args.print_top > 0):
        total = len(ranked)
        total_edges = sum(len(out_edges[cid]) for cid in out_edges)
        avg_in = sum(len(in_edges[cid]) for cid in in_edges) / float(total) if total else 0.0
        avg_out = sum(len(out_edges[cid]) for cid in out_edges) / float(total) if total else 0.0
        max_in = max((len(in_edges[cid]) for cid in in_edges), default=0)
        max_out = max((len(out_edges[cid]) for cid in out_edges), default=0)

        bet_mode = "disabled" if bet_samples < 0 else ("exact" if bet_samples == 0 else f"sampled({bet_samples})")

        print("CIS filtering summary")
        print(f"- Total components      : {total}")
        print(f"- Repo-internal edges    : {total_edges}")
        print(f"- Avg in/out degree      : {avg_in:.2f} / {avg_out:.2f}")
        print(f"- Max in/out degree      : {max_in} / {max_out}")
        print(f"- Kept top-percent       : {args.top_percent}%  (kept={len(selected)})")
        print(f"- Weights (a,b,g)        : {args.alpha}, {args.beta}, {args.gamma}")
        print(f"- Betweenness mode       : {bet_mode}")
        print(f"- PageRank damping/iters : {args.pagerank_damping} / {args.pagerank_iters}")

        # Determine how many to print
        if args.print_top_percent and args.print_top_percent > 0:
            requested = float(args.print_top_percent)
            effective = min(requested, float(args.top_percent))
            k = int(math.ceil(total * (effective / 100.0)))
            k = max(1, min(k, len(selected) if selected else total))
            print(f"- Print top-percent      : {requested}% (effective={effective}%, count={k})")
        else:
            k = min(int(args.print_top), total)
            print(f"- Print top-count        : {k}")

        print("\nTop components by CIS score:")
        # Only print among selected when percent-based to stay consistent with filtering
        if args.print_top_percent and args.print_top_percent > 0:
            selected_set = set(selected)
            printable = [cid for cid in ranked if cid in selected_set]
        else:
            printable = ranked

        for i, cid in enumerate(printable[:k]):
            m = metrics[cid]
            print(
                f"{i+1:>3}. {cid} | score={m.score:.6f} | in={m.in_degree} out={m.out_degree} "
                f"bc={m.betweenness:.6f} pr={m.pagerank:.6f}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
