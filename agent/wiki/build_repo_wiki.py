from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .recursive_system import RecursiveRepoWikiSystem


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate repo_wiki Markdown outputs")
    parser.add_argument(
        "--wiki-mode",
        choices=["distributed", "monolithic", "both"],
        default="both",
        help="Output format: 'distributed' (multi-page), 'monolithic' (single WIKI.md), or 'both'",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Ignore cache and recompute all stages",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Do not read cached stage outputs",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    system = RecursiveRepoWikiSystem(project_root=project_root)

    # Quick input checks
    paths = system.paths
    required = [
        paths.readme_path,
        paths.components_path,
        paths.dependency_graph_path,
        paths.tree_path,
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        print("Missing required inputs:", file=sys.stderr)
        for m in missing:
            print(f"- {m}", file=sys.stderr)
        return 2

    system.run(
        use_cache=not args.no_cache,
        force_rebuild=bool(args.force_rebuild),
        wiki_mode=str(args.wiki_mode),
    )
    print(f"repo_wiki generated at: {paths.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
