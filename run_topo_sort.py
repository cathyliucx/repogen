from __future__ import annotations
import yaml
from pathlib import Path

from dependency_analyzer.ast_parser import DependencyParser
from dependency_analyzer.topo_sort import build_graph_from_components, topological_sort, dependency_first_dfs
def main():

    config_path = Path(__file__).parent / "config/data_config.yaml"
    
    if not config_path.exists():
        print(f"Error: Configuration file not found at {config_path}")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 2. Extract Parameters from YAML
    # We use .get() for safer access to nested keys
    repo_dir = config.get("repo_dir")
    out_dir = config.get("out_dir")
    out_json = config.get("ast_out_json")

    # 3. Validation & Directory Setup
    if not all([repo_dir, out_dir, out_json]):
        print("Error: Missing required paths in data_config.yaml")
        return

    # 3. Parse components + dependencies
    parser = DependencyParser(str(repo_dir))
    components = parser.parse_repository()

    # 4. Build a dependency graph (A -> deps)
    graph = build_graph_from_components(components)

    # 5. Compute orders
    order_kahn = topological_sort(graph)
    order_dfs = dependency_first_dfs(graph)

    print(f"Repo: {repo_dir}")
    print(f"Components: {len(components)}")
    print(f"Graph nodes: {len(graph)}")

    print("\n=== Topological order (kahn-style, deps-first) ===")
    for node in order_kahn[:25]:
        print(node)
    if len(order_kahn) > 25:
        print(f"... ({len(order_kahn)} total)")

    print("\n=== Dependency-first DFS order ===")
    for node in order_dfs[:25]:
        print(node)
    if len(order_dfs) > 25:
        print(f"... ({len(order_dfs)} total)")

if __name__ == "__main__":
    main()
