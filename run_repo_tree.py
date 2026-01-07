from __future__ import annotations
import os
from pathlib import Path
import importlib.util
import json
import yaml
from data_process.repo_tree import ProjectStructureGenerator


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
    repo_dir = config.get("repo_dir", "data/raw_test_repo")
    out_dir = config.get("out_dir", "data/meta_test_repo")
    out_json = os.path.join(out_dir, "repo_tree.json")

    # 3. Validation & Directory Setup
    if not all([repo_dir, out_dir]):
        print("Error: Missing required paths in data_config.yaml")
        return

    # 4. Ensure output directory exists before saving
    os.makedirs(out_dir, exist_ok=True)

    # 5. Generate Project Structure
    generator = ProjectStructureGenerator()
    structure = generator.generate_structure(repo_dir, max_depth=6)

    print("=== TEXT TREE ===")
    print(generator.format_structure(structure))
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(structure, f, ensure_ascii=False, indent=2)

    print("\n=== JSON WRITTEN ===")
    print(out_json)

if __name__ == "__main__":
    main()
