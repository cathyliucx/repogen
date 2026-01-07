"""
Topological sorting utilities for dependency graphs with cycle handling.

This module provides functions to perform topological sorting on a dependency graph,
including detection and resolution of dependency cycles.
"""

import logging
import json
from typing import Dict, List, Set, Tuple, Any, Optional
from collections import defaultdict
import heapq

logger = logging.getLogger(__name__)


def _normalize_graph(graph: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    """Return a copy of the graph that includes all referenced nodes.

    The input graph uses the "natural" dependency direction:
    - If A depends on B, there is an edge A -> B (B is in graph[A]).

    Some nodes may appear only as dependencies; this function ensures they are
    present as keys with an empty dependency set.
    """
    normalized: Dict[str, Set[str]] = {node: set(deps) for node, deps in graph.items()}
    for node, deps in list(normalized.items()):
        for dep in deps:
            if dep not in normalized:
                normalized[dep] = set()
    return normalized

def detect_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    """
    Detect cycles in a dependency graph using Tarjan's algorithm to find
    strongly connected components.
    
    Args:
        graph: A dependency graph represented as adjacency lists
               (node -> set of dependencies)
    
    Returns:
        A list of lists, where each inner list contains the nodes in a cycle.
        Includes self-loops (a node that depends on itself).
    """
    graph = _normalize_graph(graph)

    # Implementation of Tarjan's algorithm
    index_counter = [0]
    index = {}  # node -> index
    lowlink = {}  # node -> lowlink value
    onstack = set()  # nodes currently on the stack
    stack = []  # stack of nodes
    result = []  # list of cycles (strongly connected components)
    
    def strongconnect(node):
        # Set the depth index for node
        index[node] = index_counter[0]
        lowlink[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        onstack.add(node)
        
        # Consider successors
        for successor in graph.get(node, set()):
            if successor not in index:
                # Successor has not yet been visited; recurse on it
                strongconnect(successor)
                lowlink[node] = min(lowlink[node], lowlink[successor])
            elif successor in onstack:
                # Successor is on the stack and hence in the current SCC
                lowlink[node] = min(lowlink[node], index[successor])
        
        # If node is a root node, pop the stack and generate an SCC
        if lowlink[node] == index[node]:
            # Start a new strongly connected component
            scc = []
            while True:
                successor = stack.pop()
                onstack.remove(successor)
                scc.append(successor)
                if successor == node:
                    break
            
            # SCCs with >1 node are cycles. Also treat self-loops as cycles.
            if len(scc) > 1:
                result.append(scc)
            elif len(scc) == 1:
                only = scc[0]
                if only in graph.get(only, set()):
                    result.append(scc)
    
    # Visit each node
    for node in graph:
        if node not in index:
            strongconnect(node)
    
    return result

def resolve_cycles(graph: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    """
    Resolve cycles in a dependency graph by identifying strongly connected
    components and breaking cycles.
    
    Args:
        graph: A dependency graph represented as adjacency lists
               (node -> set of dependencies)
    
    Returns:
        A new acyclic graph with the same nodes but with cycles broken
    """
    new_graph = _normalize_graph(graph)

    # Iteratively break cycles until none remain (or we stop making progress)
    removed_edges: List[Tuple[str, str]] = []
    max_rounds = max(10, len(new_graph) * 2)

    for round_idx in range(max_rounds):
        cycles = detect_cycles(new_graph)
        if not cycles:
            if removed_edges:
                logger.info(
                    "Resolved cycles by removing %d edge(s): %s",
                    len(removed_edges),
                    ", ".join(f"{u}->{v}" for u, v in removed_edges),
                )
            else:
                logger.info("No cycles detected in the dependency graph")
            return new_graph

        logger.info(f"Detected {len(cycles)} cycle group(s) in the dependency graph")
        changed_this_round = False

        for i, scc in enumerate(cycles):
            scc_set = set(scc)
            logger.info(f"Cycle group {i+1}: {', '.join(sorted(scc_set))}")

            # Break self-loops first (deterministic)
            for u in sorted(scc_set):
                if u in new_graph.get(u, set()):
                    logger.info(f"Breaking self-loop by removing dependency: {u} -> {u}")
                    new_graph[u].remove(u)
                    removed_edges.append((u, u))
                    changed_this_round = True
                    break
            if changed_this_round:
                continue

            # Pick and remove one intra-SCC dependency edge (u -> v where both in SCC)
            removed = False
            for u in sorted(scc_set):
                for v in sorted(new_graph.get(u, set())):
                    if v in scc_set:
                        logger.info(f"Breaking cycle by removing dependency: {u} -> {v}")
                        new_graph[u].remove(v)
                        removed_edges.append((u, v))
                        changed_this_round = True
                        removed = True
                        break
                if removed:
                    break

        if not changed_this_round:
            logger.warning("Cycle resolution stopped making progress; returning partially-resolved graph")
            return new_graph

    logger.warning("Cycle resolution exceeded max rounds; returning partially-resolved graph")
    return new_graph

def topological_sort(graph: Dict[str, Set[str]]) -> List[str]:
    """
    Perform a topological sort on a dependency graph.
    
    Args:
        graph: A dependency graph represented as adjacency lists
               (node -> set of dependencies)
    
    Returns:
        A list of nodes in topological order (dependencies first)
    """
    # Graph convention: A -> B means "A depends on B".
    # We want an order where dependencies come first.
    # Convert to prerequisite edges: B -> A ("B must come before A").
    acyclic_graph = resolve_cycles(graph)
    acyclic_graph = _normalize_graph(acyclic_graph)

    dependents: Dict[str, Set[str]] = defaultdict(set)
    in_degree: Dict[str, int] = {node: 0 for node in acyclic_graph}

    for node, deps in acyclic_graph.items():
        for dep in deps:
            dependents[dep].add(node)
            in_degree[node] += 1

    # Nodes with no prerequisites (no dependencies) come first.
    # Use a heap to keep order deterministic.
    heap: List[str] = [node for node, degree in in_degree.items() if degree == 0]
    heapq.heapify(heap)
    result: List[str] = []

    while heap:
        node = heapq.heappop(heap)
        result.append(node)
        for dependent in sorted(dependents.get(node, set())):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                heapq.heappush(heap, dependent)

    if len(result) != len(acyclic_graph):
        logger.warning("Topological sort incomplete after cycle resolution; returning best-effort order")
        remaining = [n for n in acyclic_graph.keys() if n not in set(result)]
        result.extend(sorted(remaining))

    return result

def dependency_first_dfs(graph: Dict[str, Set[str]]) -> List[str]:
    """
    Perform a depth-first traversal of the dependency graph.
    
    The graph uses natural dependency direction:
    - If A depends on B, the graph has an edge A → B
    - This means an edge from X to Y represents "X depends on Y"
        - We ensure a node appears after all of its dependencies.
    
    Args:
        graph: A dependency graph with natural direction (A→B if A depends on B)
    
    Returns:
        A list of nodes in an order where dependencies come before their dependents
    """
    # First, resolve cycles to ensure we have a DAG
    acyclic_graph = resolve_cycles(graph)
    acyclic_graph = _normalize_graph(acyclic_graph)

    visited: Set[str] = set()
    visiting: Set[str] = set()
    result: List[str] = []

    def dfs(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            # Should not happen after resolve_cycles(), but guard anyway
            return
        visiting.add(node)
        for dep in sorted(acyclic_graph.get(node, set())):
            dfs(dep)
        visiting.remove(node)
        visited.add(node)
        result.append(node)

    # Visit every node to ensure full coverage (with A->deps graphs, starting only from deps-free nodes is insufficient).
    for node in sorted(acyclic_graph.keys()):
        dfs(node)

    return result

def build_graph_from_components(components: Dict[str, Any]) -> Dict[str, Set[str]]:
    """
    Build a dependency graph from a collection of code components.
    
    The graph uses the natural dependency direction:
    - If A depends on B, we create an edge A → B
    - This means an edge from node X to node Y represents "X depends on Y"
    - Root nodes (nodes with no dependencies) are components that don't depend on anything
    
    Args:
        components: A dictionary of code components, where each component
                   has a 'depends_on' attribute
    
    Returns:
        A dependency graph with natural dependency direction
    """
    graph = {}
    
    for comp_id, component in components.items():
        # Initialize the node's adjacency list
        if comp_id not in graph:
            graph[comp_id] = set()
        
        # Add dependencies
        for dep_id in component.depends_on:
            # Only include dependencies that are actual components in our repository
            if dep_id in components:
                graph[comp_id].add(dep_id)
    
    return graph 
