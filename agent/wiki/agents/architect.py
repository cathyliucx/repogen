from __future__ import annotations
import tiktoken
from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Optional
import tiktoken

from ...base import BaseAgent
from ..utils import safe_json_loads
from .utils import truncate_tokens, get_agent_token_limits


class ArchitectAgent(BaseAgent):
    """Infer architecture insights from dependency graph + module-level semantic summaries."""

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="architect", config_path=config_path)

    def process(self, ast_graph: dict[str, Any], module_summaries: dict[str, Any]) -> list[str]:
        # NOTE: In this repo, `ast_graph` (from dependency_graph_path) is typically
        # a mapping: component_id -> serialized CodeComponent dict.
        # We treat the component graph as bottom-level evidence, then aggregate it
        # into file-level and package-level (top-level dir) module graphs.

        def _as_list(x: Any) -> list[Any]:
            if x is None:
                return []
            if isinstance(x, list):
                return x
            if isinstance(x, (set, tuple)):
                return list(x)
            return [x]

        def _truncate(text: str, limit_tokens: int) -> str:
            # get_agent_token_limits must return ints
            max_input_tokens, max_output_tokens = get_agent_token_limits(self)
            if not isinstance(max_input_tokens, int) or not isinstance(max_output_tokens, int):
                raise RuntimeError("Agent token limits not found. get_agent_token_limits must return ints.")
            # limit_tokens is token count（caller must pass token count, e.g. 60)
            return truncate_tokens(text, limit_tokens)
            if len(text) <= limit:
                return text
            return text[: max(0, limit - 1)].rstrip() + "…"

        def _is_serialized_component(v: Any) -> bool:
            return isinstance(v, dict) and (
                "relative_path" in v or "component_type" in v or "file_path" in v or "docstring" in v
            )

        # Build component adjacency (A -> deps) and component -> file mapping.
        component_ids = set(ast_graph.keys())
        comp_deps: dict[str, set[str]] = {}
        comp_file: dict[str, str] = {}
        comp_type: dict[str, str] = {}
        comp_has_doc: dict[str, bool] = {}
        comp_doc: dict[str, str] = {}

        for comp_id, v in ast_graph.items():
            depends = []
            if isinstance(v, dict):
                depends = _as_list(v.get("depends_on") or [])
                rel = v.get("relative_path")
                if isinstance(rel, str) and rel.strip():
                    comp_file[comp_id] = rel.strip()
                ctype = v.get("component_type")
                if isinstance(ctype, str):
                    comp_type[comp_id] = ctype
                comp_has_doc[comp_id] = bool(v.get("has_docstring"))
                d = v.get("docstring")
                if isinstance(d, str):
                    comp_doc[comp_id] = d
            else:
                # Fallback: treat as a graph node with a `depends_on` attribute.
                depends = _as_list(getattr(v, "depends_on", []))

            # Keep only dependencies that are components in this repo.
            dep_set = {str(d) for d in depends if isinstance(d, str) and d in component_ids}
            comp_deps[comp_id] = dep_set

        # If values are not serialized components, assume this is already a graph of nodes with depends_on.
        # In that case, treat each node id as a "module" and keep the old behavior.
        if ast_graph and not _is_serialized_component(next(iter(ast_graph.values()))):
            in_deg: dict[str, int] = {k: 0 for k in ast_graph}
            out_deg: dict[str, int] = {k: len((v.get("depends_on") or [])) for k, v in ast_graph.items() if isinstance(v, dict)}
            for src, v in ast_graph.items():
                if not isinstance(v, dict):
                    continue
                for dep in v.get("depends_on") or []:
                    if dep in in_deg:
                        in_deg[dep] += 1
            hubs = sorted(ast_graph.keys(), key=lambda k: (in_deg.get(k, 0), out_deg.get(k, 0)), reverse=True)
            hub_lines = "\n".join(f"- {h} (in={in_deg.get(h,0)} out={out_deg.get(h,0)})" for h in hubs[:50])

            module_lines = "\n".join(
                f"- {m}: {str(s.get('module_summary',''))}" for m, s in list(module_summaries.items())
            )
        else:
            # ---- Aggregation: component -> file module ----
            def file_of(comp_id: str) -> str:
                rel = comp_file.get(comp_id)
                return rel if rel else "(unknown)"

            def package_of(file_rel: str) -> str:
                if file_rel in ("", "(unknown)"):
                    return "(unknown)"
                parts = Path(file_rel).parts
                return "(root)" if len(parts) <= 1 else parts[0]

            comp_package: dict[str, str] = {}
            for cid in component_ids:
                f = file_of(cid)
                comp_package[cid] = package_of(f)

            # External incoming (cross-file) counts per component for representative selection.
            external_in_count: DefaultDict[str, int] = defaultdict(int)
            external_in_files: DefaultDict[str, set[str]] = defaultdict(set)

            # Fold component edges into file->file and package->package edges.
            file_edge_counts: DefaultDict[tuple[str, str], int] = defaultdict(int)
            pkg_edge_counts: DefaultDict[tuple[str, str], int] = defaultdict(int)

            for src, deps in comp_deps.items():
                src_file = file_of(src)
                src_pkg = comp_package.get(src, "(unknown)")
                for dep in deps:
                    dep_file = file_of(dep)
                    dep_pkg = comp_package.get(dep, "(unknown)")
                    if src_file != dep_file:
                        file_edge_counts[(src_file, dep_file)] += 1
                        external_in_count[dep] += 1
                        external_in_files[dep].add(src_file)
                    if src_pkg != dep_pkg:
                        pkg_edge_counts[(src_pkg, dep_pkg)] += 1

            def _degree_from_edges(edge_counts: dict[tuple[str, str], int]) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
                unique_in: DefaultDict[str, set[str]] = defaultdict(set)
                unique_out: DefaultDict[str, set[str]] = defaultdict(set)
                weighted_in: DefaultDict[str, int] = defaultdict(int)
                weighted_out: DefaultDict[str, int] = defaultdict(int)
                for (src_m, dep_m), w in edge_counts.items():
                    unique_out[src_m].add(dep_m)
                    unique_in[dep_m].add(src_m)
                    weighted_out[src_m] += w
                    weighted_in[dep_m] += w
                return (
                    {k: len(v) for k, v in unique_in.items()},
                    {k: len(v) for k, v in unique_out.items()},
                    dict(weighted_in),
                    dict(weighted_out),
                )

            pkg_unique_in, pkg_unique_out, pkg_weighted_in, pkg_weighted_out = _degree_from_edges(pkg_edge_counts)

            # Rank "hub" packages by weighted in/out, then unique degrees.
            all_pkgs = set()
            for (a, b) in pkg_edge_counts.keys():
                all_pkgs.add(a)
                all_pkgs.add(b)
            for cid in component_ids:
                all_pkgs.add(comp_package.get(cid, "(unknown)"))

            hubs = sorted(
                all_pkgs,
                key=lambda k: (
                    pkg_weighted_in.get(k, 0),
                    pkg_weighted_out.get(k, 0),
                    pkg_unique_in.get(k, 0),
                    pkg_unique_out.get(k, 0),
                ),
                reverse=True,
            )

            hub_lines = "\n".join(
                f"- {p} (in_w={pkg_weighted_in.get(p,0)} out_w={pkg_weighted_out.get(p,0)} in_u={pkg_unique_in.get(p,0)} out_u={pkg_unique_out.get(p,0)})"
                for p in hubs[:20]
            )

            # Strongest package dependencies (by folded edge weight)
            strongest_pkg_edges = sorted(pkg_edge_counts.items(), key=lambda kv: kv[1], reverse=True)[:40]
            pkg_edge_lines = "\n".join(f"- {a} -> {b} (w={w})" for (a, b), w in strongest_pkg_edges)

            # Representative symbols: per file, then present grouped by package.
            def _is_public_symbol(comp_id: str) -> bool:
                last = comp_id.split(".")[-1]
                return not last.startswith("_")

            def _is_class_or_function(cid: str) -> bool:
                return comp_type.get(cid) in ("class", "function")

            # Group by file
            by_file: DefaultDict[str, list[str]] = defaultdict(list)
            for cid in component_ids:
                by_file[file_of(cid)].append(cid)

            reps_by_file: dict[str, list[str]] = {}
            for f, cids in by_file.items():
                candidates = [
                    cid
                    for cid in cids
                    if _is_class_or_function(cid) and _is_public_symbol(cid)
                ]
                if not candidates:
                    continue

                def score(cid: str) -> tuple[int, int, int, int, str]:
                    callers = len(external_in_files.get(cid, set()))
                    ext = external_in_count.get(cid, 0)
                    has_doc = 1 if comp_has_doc.get(cid, False) and (comp_doc.get(cid) or "").strip() else 0
                    ctype_bias = 1 if comp_type.get(cid) == "class" else 0
                    return (callers, ext, has_doc, ctype_bias, cid)

                top = sorted(candidates, key=score, reverse=True)[:8]
                reps_by_file[f] = top

            # Render representative symbols grouped by package -> file
            pkg_to_files: DefaultDict[str, set[str]] = defaultdict(set)
            for f in reps_by_file.keys():
                pkg_to_files[package_of(f)].add(f)

            rep_lines: list[str] = []
            for pkg in sorted(pkg_to_files.keys()):
                rep_lines.append(f"# {pkg}")
                for f in sorted(pkg_to_files[pkg]):
                    rep_lines.append(f"- {f}")
                    for cid in reps_by_file.get(f, []):
                        callers = len(external_in_files.get(cid, set()))
                        ext = external_in_count.get(cid, 0)
                        doc = (comp_doc.get(cid) or "").strip()
                        doc_snip = _truncate(" ".join(doc.split()), 60) if doc else ""
                        suffix = f" | doc: {doc_snip}" if doc_snip else ""
                        rep_lines.append(f"  - {cid} ({comp_type.get(cid,'?')}, external_callers={callers}, external_edges={ext}){suffix}")

            # Do NOT truncate module_summary (semantic anchors are top-level directories).
            module_lines = "\n".join(
                f"- {m}: {str((s or {}).get('module_summary',''))}" for m, s in list(module_summaries.items())
            )

            # Prepare a consolidated "hub" section to feed the model.
            hub_lines = (
                "Top packages by dependency degree:\n"
                + hub_lines
                + "\n\nStrongest package dependencies (folded from symbol graph):\n"
                + (pkg_edge_lines or "- (none)")
                + "\n\nRepresentative symbols (evidence; grouped by package/file):\n"
                + ("\n".join(rep_lines) if rep_lines else "- (none)")
            )

        self.clear_memory()
        self.add_to_memory(
            "system",
            "You are an Architect agent. Given a repository architecture context derived from a symbol-level dependency graph (folded into package/module relationships) "
            "and semantic module summaries, infer architecture patterns, boundaries, dependency direction, and key business flows. "
            "Use module summaries as semantic anchors; use representative symbols only as supporting evidence. "
            "Return ONLY JSON with key 'architecture_insights' (a list of strings).",
        )
        self.add_to_memory(
            "user",
            "Architecture context (from symbol graph, aggregated to modules/packages):\n"
            + str(hub_lines).rstrip()
            + "\n\nModule summaries (semantic anchors; do not ignore):\n"
            + str(module_lines).rstrip()
            + "\n\nReturn ONLY JSON.",
        )

        obj = safe_json_loads(self.generate_response())
        if isinstance(obj, dict) and isinstance(obj.get("architecture_insights"), list):
            return [str(x) for x in obj["architecture_insights"]]

        # fallback minimal
        return [
            "(architecture_insights unavailable)",
            "Hub packages: " + ", ".join(hubs[:6]),
        ]
