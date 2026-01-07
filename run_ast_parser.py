import yaml
import os
from pathlib import Path
from dependency_analyzer.ast_parser import DependencyParser

def main():
    # 1. Locate and Load Configuration
    # Using Path(__file__) ensures the config is found relative to the script
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
    out_json = os.path.join(out_dir, "/dependency_graph.json")

    # 3. Validation & Directory Setup
    if not all([repo_dir, out_dir]):
        print("Error: Missing required paths in data_config.yaml")
        return

    # Ensure output directory exists before saving
    os.makedirs(out_dir, exist_ok=True)

    # 4. Execute Dependency Analysis
    parser = DependencyParser(str(repo_dir))
    components = parser.parse_repository()
    
    # Save results
    parser.save_dependency_graph(str(out_json))

    # 5. Output Summary
    print(f"Repo       : {repo_dir}")
    print(f"Output     : {out_json}")
    print(f"Components : {len(components)}")

    # Show a preview of components with dependencies
    for comp_id, comp in sorted(components.items()):
        deps = sorted(list(comp.depends_on))
        if not deps:
            continue
        print(f"\n- {comp_id} ({comp.component_type})")
        for dep in deps[:5]:
            print(f"  -> {dep}")

if __name__ == "__main__":
    main()