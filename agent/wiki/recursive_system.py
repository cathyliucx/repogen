from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

try:
    from tqdm import tqdm  # type: ignore
except Exception:  # pragma: no cover
    tqdm = None

from .state import RepoState
from .utils import DataPaths, read_json, write_json
from .agents.context_manager import ContextManagerAgent
from .agents.atomic_analyzer import AtomicAnalyzerAgent
from .agents.architect import ArchitectAgent
from .agents.wiki_builder import WikiBuilderAgent


class RecursiveRepoWikiSystem:
    """Implements the recursive wiki pipeline described in the spec."""
    def __init__(self, *, project_root: Path, config_path: Optional[Path] = None, data_config_path: Optional[Path] = None):
        # Pass data_config_path into DataPaths so paths are read from the provided config
        self.paths = DataPaths(project_root, data_config_path=data_config_path)
        self.config_path = config_path or (project_root / "config" / "agent_config.yaml")
        self.state: RepoState = {}

    def run(
        self,
        *,
        use_cache: bool = True,
        force_rebuild: bool = False,
        max_aggregation_level: int = 3,
        max_workers: int = 8,
        batch_size: int = 50,
        limit_doc_items: int | None = None,
        wiki_mode: str = "both",
        show_progress: bool = True,
    ) -> RepoState:
        cache_dir = self.paths.output_dir / "_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        def cache_path(name: str) -> Path:
            return cache_dir / name

        def load_if_exists(name: str):
            p = cache_path(name)
            if use_cache and (not force_rebuild) and p.exists():
                return read_json(p)
            return None

        def save(name: str, obj) -> None:
            write_json(cache_path(name), obj)

        suffix = f"_limit_{int(limit_doc_items)}" if limit_doc_items is not None else ""

        def stage(label: str):
            start = time.perf_counter()
            print(f"[Wiki] {label} ...")

            def done(extra: str = ""):
                elapsed = time.perf_counter() - start
                tail = f" ({extra})" if extra else ""
                print(f"[Wiki] {label} done in {elapsed:.1f}s{tail}")

            return done

        # --- Stage 1: README recursive context ---
        ctx_out = load_if_exists("stage_a_context.json")
        if ctx_out is None:
            done = stage("Stage A: README context (compute)")
            readme = self.paths.readme_path.read_text(encoding="utf-8", errors="replace")
            ctx_agent = ContextManagerAgent(config_path=str(self.config_path))
            ctx_out = ctx_agent.process(readme, show_progress=show_progress)
            save("stage_a_context.json", ctx_out)
            done()
        else:
            print("[Wiki] Stage A: README context (cache hit)")
        self.state["project_context_tree"] = ctx_out["context_tree"]
        identity_card = ctx_out["identity_card"]

        # --- Stage 2: Docstrings bottom-up aggregation ---
        semantic_registry = load_if_exists(f"stage_b_semantic_registry{suffix}.json")
        if semantic_registry is None:
            done = stage("Stage B: semantic registry (compute)")
            raw_items = read_json(self.paths.components_path)
            doc_items = AtomicAnalyzerAgent.normalize_input_items(raw_items)
            if limit_doc_items is not None:
                doc_items = doc_items[: int(limit_doc_items)]
            atomic_agent = AtomicAnalyzerAgent(config_path=str(self.config_path))
            semantic_registry = atomic_agent.recursive_semantic_aggregation(
                doc_items,
                repo_root=self.paths.repo_dir,
                identity_card=identity_card,
                max_level=max_aggregation_level,
                max_workers=max_workers,
                batch_size=batch_size,
                cache_dir=cache_dir,
                show_progress=show_progress,
            )
            save(f"stage_b_semantic_registry{suffix}.json", semantic_registry)
            done(extra=f"items={len(doc_items)}")
        else:
            print("[Wiki] Stage B: semantic registry (cache hit)")
        self.state["semantic_registry"] = semantic_registry

        # --- Stage 3: Architecture insights from graph + module summaries ---
        insights = load_if_exists(f"stage_c_architecture_insights{suffix}.json")
        if insights is None:
            done = stage("Stage C: architecture insights (compute)")
            ast_graph = read_json(self.paths.dependency_graph_path)
            arch_agent = ArchitectAgent(config_path=str(self.config_path))
            c_pbar = None
            if show_progress and tqdm is not None:
                c_pbar = tqdm(total=1, desc="Stage C: architecture insights", unit="step")
            try:
                insights = arch_agent.process(ast_graph, semantic_registry.get("module_summaries", {}))
            finally:
                if c_pbar is not None:
                    c_pbar.update(1)
                    c_pbar.close()
            save(f"stage_c_architecture_insights{suffix}.json", insights)
            done(extra=f"insights={len(insights) if isinstance(insights, list) else 'n/a'}")
        else:
            print("[Wiki] Stage C: architecture insights (cache hit)")
        self.state["architecture_insights"] = insights

        # --- Stage 4: Distributed wiki assembly ---
        done = stage(f"Stage D: wiki assembly ({wiki_mode})")
        tree = read_json(self.paths.tree_path)
        wiki_builder = WikiBuilderAgent(self.paths.output_dir, repo_root=self.paths.repo_dir)
        pages = wiki_builder.assemble_distributed_wiki(
            tree=tree,
            semantic_registry=semantic_registry,
            architecture_insights=insights,
            project_context_tree=self.state["project_context_tree"],
            wiki_mode=wiki_mode,
            show_progress=show_progress,
        )
        self.state["wiki_pages"] = pages
        done(extra=f"pages={len(pages)}")

        return self.state
