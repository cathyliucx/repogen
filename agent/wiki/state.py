from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class RepoState(TypedDict, total=False):
    """Shared state across wiki agents."""

    # README hierarchical summaries
    project_context_tree: Dict[str, Any]

    # semantic_registry contains:
    # - function_items: list[dict]
    # - file_summaries: dict[file_rel -> dict]
    # - module_summaries: dict[module_path -> dict]
    semantic_registry: Dict[str, Any]

    # High-level architecture insights
    architecture_insights: List[str]

    # Generated wiki pages (path -> markdown)
    wiki_pages: Dict[str, str]
