from __future__ import annotations

import ast
import shutil
from pathlib import Path
from typing import Any

try:
    from tqdm import tqdm  # type: ignore
except Exception:  # pragma: no cover
    tqdm = None

from ..utils import ensure_dir, md_link, write_text
from ...utils import strip_think_blocks


class WikiBuilderAgent:
    """Build a distributed wiki (index + directory pages + file pages) and stitch links."""

    def __init__(self, output_dir: Path, *, repo_root: Path | None = None):
        self.output_dir = output_dir
        self.pages_dir = output_dir / "pages"
        self.repo_root = repo_root

    def assemble_distributed_wiki(
        self,
        *,
        tree: dict[str, Any],
        semantic_registry: dict[str, Any],
        architecture_insights: list[str],
        project_context_tree: dict[str, Any],
        wiki_mode: str = "both",
        show_progress: bool = True,
    ) -> dict[str, str]:
        """Generate wiki outputs.

        wiki_mode:
          - distributed: INDEX.md/ARCHITECTURE.md/CONTEXT.md + pages/**
          - monolithic: a single WIKI.md only
          - both: generate both sets
        """

        ensure_dir(self.output_dir)

        pages: dict[str, str] = {}

        wiki_mode = (wiki_mode or "both").strip().lower()
        if wiki_mode not in {"distributed", "monolithic", "both"}:
            wiki_mode = "both"

        emit_distributed = wiki_mode in {"distributed", "both"}
        emit_monolithic = wiki_mode in {"monolithic", "both"}

        # If switching modes, proactively remove stale outputs from previous runs.
        # This keeps the output directory aligned with the chosen mode.
        if emit_monolithic and not emit_distributed:
            # Monolithic-only: remove distributed artifacts.
            for p in (self.output_dir / "INDEX.md", self.output_dir / "ARCHITECTURE.md", self.output_dir / "CONTEXT.md"):
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
            try:
                if self.pages_dir.exists():
                    shutil.rmtree(self.pages_dir)
            except Exception:
                pass

        if emit_distributed and not emit_monolithic:
            # Distributed-only: remove monolithic artifact.
            p = self.output_dir / "WIKI.md"
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

        # Only create pages/ when we actually emit distributed pages.
        if emit_distributed:
            ensure_dir(self.pages_dir)

        # Map file_rel -> page path (only needed for distributed mode)
        file_page: dict[str, str] = {}

        def count_files(node: dict[str, Any]) -> int:
            if node.get("type") == "file":
                return 1
            if node.get("type") == "directory":
                return sum(count_files(ch) for ch in (node.get("contents") or []))
            return 0

        total_files = count_files(tree)
        d_pbar = None
        if show_progress and tqdm is not None:
            if emit_distributed and total_files > 0:
                d_pbar = tqdm(total=total_files, desc="Stage D: wiki assembly", unit="file")
            elif emit_monolithic:
                d_pbar = tqdm(total=1, desc="Stage D: write WIKI.md", unit="step")

        def walk_files(node: dict[str, Any], prefix: str = ""):
            if node.get("type") == "file":
                rel = prefix + node.get("name")
                path = f"pages/file/{rel}.md"
                file_page[rel] = path
                if d_pbar is not None:
                    d_pbar.update(1)
                return
            if node.get("type") == "directory":
                name = node.get("name")
                new_prefix = prefix + (name + "/" if name else "")
                for ch in node.get("contents") or []:
                    walk_files(ch, new_prefix)

        if emit_distributed:
            walk_files(tree)

        if d_pbar is not None:
            d_pbar.set_description("Stage D: writing outputs")

        if emit_distributed:
            # Index
            index_md = self._render_index(tree, file_page)
            pages["INDEX.md"] = index_md
            write_text(self.output_dir / "INDEX.md", index_md)

            # Architecture page
            arch_md = "# Architecture Insights\n\n" + "\n".join(f"- {x}" for x in architecture_insights) + "\n"
            pages["ARCHITECTURE.md"] = arch_md
            write_text(self.output_dir / "ARCHITECTURE.md", arch_md)

            # Context page (README summaries)
            ctx_md = "# Project Context Tree\n\n" + self._render_context_tree(project_context_tree) + "\n"
            pages["CONTEXT.md"] = ctx_md
            write_text(self.output_dir / "CONTEXT.md", ctx_md)

        if emit_monolithic:
            # Monolithic wiki (single file)
            monolithic_md = self._render_monolithic_wiki(
                tree=tree,
                semantic_registry=semantic_registry,
                architecture_insights=architecture_insights,
                project_context_tree=project_context_tree,
            )
            pages["WIKI.md"] = monolithic_md
            write_text(self.output_dir / "WIKI.md", monolithic_md)
            if d_pbar is not None and (not emit_distributed):
                d_pbar.update(1)

        if emit_distributed:
            # Directory + file pages
            self._render_pages(tree, semantic_registry, file_page, pages)

        if d_pbar is not None:
            d_pbar.close()

        # Link stitcher: currently links are rendered inline; kept as state output.
        return pages

    def _render_monolithic_wiki(
        self,
        *,
        tree: dict[str, Any],
        semantic_registry: dict[str, Any],
        architecture_insights: list[str],
        project_context_tree: dict[str, Any],
    ) -> str:
        file_summaries = semantic_registry.get("file_summaries") or {}
        module_summaries = semantic_registry.get("module_summaries") or {}
        fn_items = semantic_registry.get("function_items") or []

        def normalize_repo_rel(path: str) -> str:
            p = str(path or "").lstrip("/")
            if not p:
                return p
            if "/" in p:
                first, rest = p.split("/", 1)
                if first and first == "raw_test_repo":
                    return rest
            return p

        # index function items by file (normalized)
        by_file: dict[str, list[dict[str, Any]]] = {}
        for it in fn_items:
            loc = str(it.get("location", "")).replace("\\", "/")
            for fr in file_summaries.keys():
                if fr and fr in loc:
                    by_file.setdefault(fr, []).append(it)
                    break

        lines: list[str] = []
        lines.append("# Repo Wiki")
        lines.append("")

        lines.append("## Project Context")
        lines.append("")
        lines.append(self._render_context_tree(project_context_tree).rstrip())
        lines.append("")

        lines.append("## Architecture Insights")
        lines.append("")
        if architecture_insights:
            lines.extend(f"- {x}" for x in architecture_insights)
        else:
            lines.append("- (architecture_insights unavailable)")
        lines.append("")

        def walk(node: dict[str, Any], prefix: str = "") -> None:
            if node.get("type") == "directory":
                name = node.get("name") or ""
                dir_path = prefix + (name + "/" if name else "")
                display_dir = dir_path.rstrip("/") or "(root)"
                # Normalize module key to match stage_b module_summaries (top-level only)
                normalized_dir = normalize_repo_rel(display_dir)
                module_key = "(root)" if normalized_dir in ("", "raw_test_repo") else normalized_dir.split("/")[0]

                lines.append(f"## Directory: {display_dir}")
                ms = module_summaries.get(module_key, {}).get("module_summary")
                if ms:
                    lines.append("")
                    lines.append(str(ms).strip())
                lines.append("")

                for ch in node.get("contents") or []:
                    walk(ch, dir_path)

            elif node.get("type") == "file":
                rel = prefix + (node.get("name") or "")
                norm = normalize_repo_rel(rel)

                lines.append(f"## File: {rel}")
                lines.append("")
                fs = file_summaries.get(norm, {})
                file_summary = fs.get("file_summary")
                if not file_summary:
                    file_summary = self._fallback_file_summary(norm) or "(no file summary)"
                lines.append(str(file_summary))

                workflows = fs.get("workflows") or []
                if workflows:
                    lines.append("")
                    lines.append("### Workflows")
                    lines.extend(f"- {w}" for w in workflows)

                items = by_file.get(norm, [])
                if items:
                    lines.append("")
                    lines.append("### Functions / Methods")
                    for it in items:
                        lines.append(f"#### {it.get('signature','(unknown)')}")
                        lines.append("")
                        lines.append(str(it.get("business_summary", "")).strip())
                        rules = it.get("business_rules") or []
                        if rules:
                            lines.append("")
                            lines.append("Business Rules")
                            lines.extend(f"- {r}" for r in rules)
                        terms = it.get("key_terms") or []
                        if terms:
                            lines.append("")
                            lines.append("Key Terms")
                            lines.extend(f"- {t}" for t in terms)

                lines.append("")

        lines.append("## Reference")
        lines.append("")
        walk(tree, "")

        return "\n".join(lines).strip() + "\n"

    def _render_index(self, tree: dict[str, Any], file_page: dict[str, str]) -> str:
        lines: list[str] = ["# Repo Wiki", "", "## Pages", ""]

        def walk(node: dict[str, Any], prefix: str = ""):
            if node.get("type") == "file":
                rel = prefix + node.get("name")
                lines.append(f"- {md_link(rel, file_page.get(rel, ''))}")
                return
            if node.get("type") == "directory":
                name = node.get("name")
                new_prefix = prefix + (name + "/" if name else "")
                for ch in node.get("contents") or []:
                    walk(ch, new_prefix)

        walk(tree)
        lines.append("")
        lines.append(f"- {md_link('Architecture', 'ARCHITECTURE.md')}")
        lines.append(f"- {md_link('Context', 'CONTEXT.md')}")
        return "\n".join(lines) + "\n"

    def _render_context_tree(self, node: dict[str, Any], depth: int = 0) -> str:
        title = node.get("title")
        summary = node.get("summary")
        children = node.get("children") or []

        lines: list[str] = []
        if depth == 0:
            pass
        else:
            indent = "  " * (depth - 1)
            if title:
                cleaned = strip_think_blocks(str(summary or "")).strip()
                summary_lines = [ln.rstrip() for ln in cleaned.splitlines() if ln.strip()]

                if not summary_lines:
                    lines.append(f"{indent}- **{title}**")
                elif len(summary_lines) == 1:
                    lines.append(f"{indent}- **{title}**: {summary_lines[0]}")
                else:
                    lines.append(f"{indent}- **{title}**:")
                    sub_indent = indent + "  "
                    for ln in summary_lines:
                        lines.append(f"{sub_indent}{ln}")

        for ch in children:
            lines.append(self._render_context_tree(ch, depth + 1))
        return "\n".join([l for l in lines if l])

    def _render_pages(self, tree: dict[str, Any], semantic_registry: dict[str, Any], file_page: dict[str, str], pages: dict[str, str]) -> None:
        fn_items = semantic_registry.get("function_items") or []
        file_summaries = semantic_registry.get("file_summaries") or {}
        module_summaries = semantic_registry.get("module_summaries") or {}

        def normalize_repo_rel(path: str) -> str:
            """Normalize wiki paths to match semantic registry keys.

            The semantic registry is keyed relative to repo_root (e.g. 'models/product.py'),
            while the wiki tree may include a leading repo directory (e.g. 'raw_test_repo/models/product.py').
            """
            p = str(path or "").lstrip("/")
            if not p:
                return p
            # If a synthetic top-level repo folder is present (e.g. 'raw_test_repo/..'), strip it.
            if "/" in p:
                first, rest = p.split("/", 1)
                if first and first == "raw_test_repo":
                    return rest
            return p

        def normalize_module_key(module_key: str) -> str:
            mk = normalize_repo_rel(module_key)
            # Stage B uses '(root)' for repo root
            return "(root)" if mk in ("", "raw_test_repo") else mk

        # index function items by file
        by_file: dict[str, list[dict[str, Any]]] = {}
        for it in fn_items:
            loc = str(it.get("location", ""))
            # location is absolute; try to infer rel from file_summaries keys
            for fr in file_summaries.keys():
                if fr and fr in loc.replace("\\", "/"):
                    by_file.setdefault(fr, []).append(it)
                    break

        def walk(node: dict[str, Any], prefix: str = ""):
            if node.get("type") == "directory":
                name = node.get("name")
                module_path = prefix + (name if name else "")
                module_key = module_path if module_path else "(root)"
                md = self._render_dir_page(normalize_module_key(module_key), node, module_summaries, file_page, prefix)
                out_path = self.pages_dir / "dir" / (module_key.replace("(root)", "root") + ".md")
                write_text(out_path, md)
                pages[str(out_path.relative_to(self.output_dir))] = md

                new_prefix = prefix + (name + "/" if name else "")
                for ch in node.get("contents") or []:
                    walk(ch, new_prefix)

            elif node.get("type") == "file":
                rel = prefix + node.get("name")
                lookup_rel = normalize_repo_rel(rel)
                md = self._render_file_page(rel, lookup_rel, file_summaries, by_file, file_page)
                out_path = self.pages_dir / "file" / f"{rel}.md"
                write_text(out_path, md)
                pages[str(out_path.relative_to(self.output_dir))] = md

        walk(tree, "")

    def _render_dir_page(
        self,
        module_key: str,
        node: dict[str, Any],
        module_summaries: dict[str, Any],
        file_page: dict[str, str],
        prefix: str,
    ) -> str:
        summary = module_summaries.get(module_key, {}).get("module_summary", "(no module summary)")
        lines: list[str] = [f"# Directory: {module_key}", "", summary, "", "## Contents", ""]

        for ch in node.get("contents") or []:
            if ch.get("type") == "directory":
                name = ch.get("name")
                sub_key = (prefix + name) if prefix else name
                target = f"pages/dir/{sub_key}.md" if sub_key else "pages/dir/root.md"
                lines.append(f"- {md_link(name + '/', target)}")
            elif ch.get("type") == "file":
                rel = prefix + ch.get("name")
                target = file_page.get(rel, "")
                lines.append(f"- {md_link(ch.get('name'), target)}")

        return "\n".join(lines).strip() + "\n"

    def _fallback_file_summary(self, lookup_rel: str) -> str | None:
        if not self.repo_root:
            return None
        try:
            path = (self.repo_root / lookup_rel)
            if not path.exists() or not path.is_file():
                return None
            if path.suffix.lower() != ".py":
                return None

            src = path.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                return "Python source file (unable to parse for summary)."

            doc = ast.get_docstring(tree) or ""
            classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
            funcs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
            has_main = "if __name__" in src

            parts: list[str] = []
            if doc.strip():
                parts.append(doc.strip().splitlines()[0].strip())
            else:
                parts.append("Python module implementing part of the repository." )

            if classes:
                shown = ", ".join(classes[:6])
                more = "" if len(classes) <= 6 else f" (+{len(classes) - 6} more)"
                parts.append(f"Defines classes: {shown}{more}.")
            if funcs:
                shown = ", ".join(funcs[:8])
                more = "" if len(funcs) <= 8 else f" (+{len(funcs) - 8} more)"
                parts.append(f"Defines functions: {shown}{more}.")
            if has_main:
                parts.append("Includes a runnable entrypoint guarded by `if __name__ == '__main__'`." )

            return " ".join(parts).strip() or None
        except Exception:
            return None

    def _render_file_page(
        self,
        display_rel: str,
        lookup_rel: str,
        file_summaries: dict[str, Any],
        by_file: dict[str, list[dict[str, Any]]],
        file_page: dict[str, str],
    ) -> str:
        fs = file_summaries.get(lookup_rel, {})
        lines: list[str] = [f"# File: {display_rel}", ""]

        file_summary = fs.get("file_summary")
        if not file_summary:
            file_summary = self._fallback_file_summary(lookup_rel) or "(no file summary)"
        lines.append(str(file_summary))

        workflows = fs.get("workflows") or []
        if workflows:
            lines.append("")
            lines.append("## Workflows")
            for w in workflows:
                lines.append(f"- {w}")

        items = by_file.get(lookup_rel, [])
        if items:
            lines.append("")
            lines.append("## Functions / Methods")
            for it in items:
                lines.append(f"### {it.get('signature','(unknown)')}")
                lines.append("")
                lines.append(str(it.get("business_summary", "")))
                rules = it.get("business_rules") or []
                if rules:
                    lines.append("")
                    lines.append("**Business Rules**")
                    for r in rules:
                        lines.append(f"- {r}")
                terms = it.get("key_terms") or []
                if terms:
                    lines.append("")
                    lines.append("**Key Terms**")
                    for t in terms:
                        lines.append(f"- {t}")
                lines.append("")

        return "\n".join(lines).strip() + "\n"
