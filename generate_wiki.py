"""
Runs the recursive Wiki pipeline against the fixture repo artifacts and prints a small preview.

Reads:
- data/raw_test_repo/README.md
- data/parsed_downloaded_repos/raw_test_repo_docstrings.jsonl
- data/parsed_downloaded_repos/raw_test_repo_dependency_graph.json
- data/parsed_downloaded_repos/raw_test_repo_tree.json

Writes:
- repo_wiki/ (INDEX.md, ARCHITECTURE.md, CONTEXT.md, pages/..)

Run (from repo root):
  python scripts/test/wiki_agent_test.py

Prereq:
- vLLM OpenAI-compatible server is running (per scripts/test/start_vllm.sh)
- config/agent_config.yaml points to the server (api_base) and served model name
"""

from __future__ import annotations
import yaml
import argparse
import json
import sys
import urllib.error
from pathlib import Path
from agent.wiki.recursive_system import RecursiveRepoWikiSystem  

def _preview_file(path: Path, *, lines: int) -> str:
    if not path.exists():
        return f"(missing: {path})"
    txt = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(txt.splitlines()[:lines])
def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RecursiveRepoWikiSystem against fixture repo")
    parser.add_argument(
        "--wiki-mode",
        choices=["distributed", "monolithic", "both"],
        default="both",
        help="Output format: 'distributed' (multi-page), 'monolithic' (single WIKI.md), or 'both'",
    )
    parser.add_argument(
        "--preview_lines",
        type=int,
        default=60,
        help="How many lines to preview from INDEX/ARCHITECTURE/CONTEXT",
    )
    parser.add_argument(
        "--dump_manifest",
        action="store_true",
        help="Write a JSON manifest of generated pages to data/parsed_downloaded_repos/_wiki_pages_manifest.json",
    )
    parser.add_argument(
        "--limit_doc_items",
        type=int,
        default=None,
        help="If set, only analyze the first N docstring items (speeds up debugging)",
    )
    parser.add_argument(
        "--max_workers",
        type=int,
        default=8,
        help="Max parallel LLM calls for Agent B (thread pool)",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=50,
        help="Batch size for Agent B parallel processing",
    )
    parser.add_argument(
        "--max_level",
        type=int,
        default=3,
        help="Aggregation depth: 1=function only, 2=+file, 3=+top-level module",
    )
    parser.add_argument(
        "--no_cache",
        action="store_true",
        help="Disable disk cache under repo_wiki/_cache",
    )
    parser.add_argument(
        "--force_rebuild",
        action="store_true",
        help="Ignore existing cache and rebuild stages",
    )
    parser.add_argument(
        "--check_llm",
        action="store_true",
        help="Preflight-check vLLM endpoint by calling GET {api_base}/models with a short timeout",
    )
    return parser.parse_args(argv)

def main() -> int:
    args = _parse_args(sys.argv[1:])
    repo_root = Path(__file__).parent
    agent_config_path = repo_root / "config" / "agent_config.yaml"
    data_config_path = repo_root / "config" / "data_config.yaml"

    with open(data_config_path, "r", encoding="utf-8") as f:
        data_config = yaml.safe_load(f)

    wiki_dir = Path(data_config.get("out_dir", "data/meta_test_repo")) / "repo_wiki"

    system = RecursiveRepoWikiSystem(
        project_root=repo_root,
        config_path=agent_config_path,
        data_config_path=data_config_path)
    
    print("[Wiki Usecase] Config:", data_config_path)
    print("[Wiki Usecase] Output dir:", wiki_dir)
    print(
        "[Wiki Usecase] Settings:",
        {
            "wiki_mode": args.wiki_mode,
            "use_cache": not args.no_cache,
            "force_rebuild": args.force_rebuild,
            "limit_doc_items": args.limit_doc_items,
            "max_workers": args.max_workers,
            "batch_size": args.batch_size,
            "max_level": args.max_level,
        },
    )

    print("[Wiki Usecase] Calling LLM via vLLM...")
    state = system.run(
        use_cache=not args.no_cache,
        force_rebuild=args.force_rebuild,
        wiki_mode=args.wiki_mode,
        limit_doc_items=args.limit_doc_items,
        max_workers=args.max_workers,
        batch_size=args.batch_size,
        max_aggregation_level=args.max_level,
    )

    # Preview
    print("\n===== repo_wiki Preview =====\n")

    mode = str(args.wiki_mode or "both").lower().strip()
    if mode in {"monolithic"}:
        wiki_path = wiki_dir / "WIKI.md"
        print("--- WIKI.md (preview) ---")
        print(_preview_file(wiki_path, lines=args.preview_lines))
    else:
        index_path = wiki_dir / "INDEX.md"
        arch_path = wiki_dir / "ARCHITECTURE.md"
        ctx_path = wiki_dir / "CONTEXT.md"

        print("--- INDEX.md (preview) ---")
        print(_preview_file(index_path, lines=args.preview_lines))
        print("\n--- ARCHITECTURE.md (preview) ---")
        print(_preview_file(arch_path, lines=args.preview_lines))
        print("\n--- CONTEXT.md (preview) ---")
        print(_preview_file(ctx_path, lines=args.preview_lines))

    pages = state.get("wiki_pages") or {}
    print("\n[Wiki Usecase] Generated page count:", len(pages))

    # Print a stable-ish sample list
    sample = sorted(pages.keys())[:40]
    if sample:
        print("[Wiki Usecase] Sample generated pages:")
        for p in sample:
            print("-", p)

    if args.dump_manifest:
        manifest_path = repo_root / "data" / "meta_test_repo" / "wiki_pages_manifest.json"
        manifest_path.write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[Wiki Usecase] Wrote manifest:", manifest_path)

if __name__ == "__main__":
    main()
