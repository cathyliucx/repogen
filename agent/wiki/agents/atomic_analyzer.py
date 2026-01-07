from __future__ import annotations
import tiktoken
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from ...base import BaseAgent
from ..utils import safe_json_loads, strip_examples_section, normalize_ws
from ..rag import LocalRag
from .utils import truncate_tokens, get_agent_token_limits


@dataclass
class FunctionSemantic:
    location: str
    signature: str
    kind: str
    business_summary: str
    business_rules: list[str]
    key_terms: list[str]


class AtomicAnalyzerAgent(BaseAgent):
    """Docstring -> business semantics; then bottom-up aggregation file -> module."""

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="atomic_analyzer", config_path=config_path)
        self._config_path = config_path

    def process(
        self,
        doc_items: list[dict[str, Any]],
        *,
        repo_root: Path,
        identity_card: dict[str, Any],
    ) -> dict[str, Any]:
        return self.recursive_semantic_aggregation(doc_items, repo_root=repo_root, identity_card=identity_card)

    @staticmethod
    def normalize_input_items(raw: Any) -> list[dict[str, Any]]:
        """Normalize supported input formats into the doc_item schema.

        Supported inputs:
        - dict[str, dict]: filtered components JSON where the key is component_id
          and values include component_type, file_path, docstring, etc.

        Note:
        This agent intentionally no longer supports docstrings JSONL (list input).
        """
        if raw is None:
            return []

        # New format: filtered components -> dict mapping component_id -> component dict
        if isinstance(raw, dict):
            out = []
            for comp_id, comp in raw.items():
                if not isinstance(comp, dict):
                    continue
                component_type = str(comp.get("component_type", "")).strip().lower()
                # Map into the doc_item fields used by this agent
                kind = component_type or "component"

                # Create a readable signature so _extract_name() can work.
                short_name = str(comp_id).split(".")[-1]
                if kind == "class":
                    signature = f"class {short_name}"
                else:
                    signature = f"def {short_name}(...)"

                out.append(
                    {
                        "type": kind,
                        "location": comp.get("file_path") or comp.get("location") or "",
                        "repo_name": comp.get("repo_name"),
                        "content": comp.get("docstring") or comp.get("content") or "",
                        "signature": signature,
                        "component_id": comp.get("id") or comp_id,
                        "relative_path": comp.get("relative_path"),
                    }
                )
            return out

        return []

    def _select_relevant_text(self, content: str, identity_card: dict[str, Any], *, max_chars: int = 8000) -> str:
        """Use a lightweight local RAG helper to extract salient chunks for long docstrings.
    
        Strict token-budget behaviour: requires `get_agent_token_limits` to return integers
        and `truncate_tokens` (which requires tiktoken) to be available. Will raise if
        these prerequisites are not met.
        """
        content = content.strip()
        # Short docs: return unchanged (still enforce token config so callers know limits exist)
        max_input_tokens, max_output_tokens = get_agent_token_limits(self)
        if not isinstance(max_input_tokens, int) or not isinstance(max_output_tokens, int):
            raise RuntimeError(
                "Agent token limits not found. `get_agent_token_limits` must return "
                "(max_input_tokens:int, max_output_tokens:int)."
            )
    
        # Reserve output tokens and overhead; give doc up to ~60% of remaining input budget
        reserve = int(max_output_tokens * 0.5) + 128
        input_budget = max(256, max_input_tokens - reserve)
        doc_budget = max(256, int(input_budget * 0.6))  # doc budget in tokens
    
        # If the content is already small enough in chars, still do a token-based final check/truncation:
        # We can't cheaply count tokens here without calling the tokenizer, so if content is probably small:
        try:
            # If content already within token budget, return it (truncate_tokens will no-op if <=)
            small_check = truncate_tokens(content, doc_budget)
            # If truncate_tokens succeeded and returned the same text, it's already within budget.
            if small_check == content:
                return content
            # Otherwise fall through to RAG-based selection using full content as source
        except Exception:
            # truncate_tokens will raise if tiktoken missing; bubble up per strict policy
            raise
    
        # Build RAG over the docstring itself
        rag = LocalRag(device="cpu", chunk_size=1200, overlap=150)
        rag.add_text(content, source="docstring")
        rag.build()
    
        domain = str(identity_card.get("domain", "")).strip()
        glossary = identity_card.get("business_terms") or {}
        glossary_keys = ", ".join(list(glossary.keys())[:])
    
        queries = [
            f"{domain} business purpose summary description",
            f"{domain} business rules constraints invariants",
            f"parameters args returns raises input output {glossary_keys}",
        ]
    
        picked: list[str] = []
        seen = set()
        # Stop collecting once we've reached a reasonable char-sized approximation
        # of the token budget. We use 1 token ~= 4 chars as approximation.
        approx_char_limit = max(512, doc_budget * 4)
    
        for q in queries:
            for ch in rag.query(q, k=4):
                txt = (ch.text or "").strip()
                if not txt or txt in seen:
                    continue
                seen.add(txt)
                picked.append(txt)
                # stop early if we've likely reached the token budget (char approx)
                if sum(len(x) for x in picked) >= approx_char_limit:
                    break
            if sum(len(x) for x in picked) >= approx_char_limit:
                break
    
        text = "\n\n".join(picked).strip()
    
        # If RAG picked nothing, or picks are empty, fall back to truncating original content
        if not text:
            return truncate_tokens(content, doc_budget)
    
        # Final truncation to token budget (strict; will raise if tiktoken missing)
        return truncate_tokens(text, doc_budget)

    def _extract_name(self, signature: str) -> str:
        m = re.search(r"\b([A-Za-z_]\w*)\s*\(", signature)
        return m.group(1) if m else ""

    def _is_trivial(self, doc_item: dict[str, Any]) -> bool:
        signature = str(doc_item.get("signature", ""))
        name = self._extract_name(signature).lower()
        kind = str(doc_item.get("type", "")).lower()
        content = normalize_ws(strip_examples_section(str(doc_item.get("content", ""))))

        if not name:
            return False

        # Skip low-signal dunder and obvious accessors
        if name in {"__repr__", "__str__", "__len__", "__iter__", "__getitem__", "__setitem__"}:
            return True

        if name.startswith(("get_", "set_", "is_", "has_")):
            # If docstring is tiny, this is very likely a trivial accessor
            return len(content) < 80

        # Very small docstrings with generic wording tend to be low value
        if kind in {"function", "method"} and len(content) < 40:
            generic = {"getter", "setter", "returns", "return", "get", "set"}
            if any(w in content.lower() for w in generic):
                return True

        return False

    def analyze_doc_item(self, doc_item: dict[str, Any], identity_card: dict[str, Any]) -> FunctionSemantic:
        content = strip_examples_section(str(doc_item.get("content", "")))
        signature = str(doc_item.get("signature", ""))
        kind = str(doc_item.get("type", ""))

        # If docstring is very long, avoid blind truncation by selecting relevant chunks.
        content = self._select_relevant_text(content, identity_card, max_chars=8000)

        glossary = identity_card.get("business_terms") or {}
        glossary_txt = "\n".join(f"- {k}: {v}" for k, v in list(glossary.items())[:])

        self.clear_memory()
        self.add_to_memory(
            "system",
            "You are an Atomic Analyzer. Convert a technical docstring into business semantics. "
            "Translate technical terms into domain terms using the glossary. "
            "Return ONLY JSON with keys: business_summary, business_rules, key_terms. "
            "business_rules must be short, testable statements.",
        )
        self.add_to_memory(
            "user",
            f"Identity domain: {identity_card.get('domain','unknown')}\n"
            f"Glossary:\n{glossary_txt}\n\n"
            f"Doc item: type={kind} signature={signature} location={doc_item.get('location')}\n\n"
            f"Docstring (examples removed):\n{content}\n\nReturn ONLY JSON.",
        )
        raw = self.generate_response()
        obj = safe_json_loads(raw)

        business_summary = ""
        business_rules: list[str] = []
        key_terms: list[str] = []

        if isinstance(obj, dict):
            business_summary = str(obj.get("business_summary", ""))
            business_rules = [normalize_ws(str(x)) for x in (obj.get("business_rules") or [])]
            key_terms = [normalize_ws(str(x)) for x in (obj.get("key_terms") or [])]

        if not business_summary:
            business_summary = normalize_ws(content.splitlines()[0] if content else "(no docstring)")

        return FunctionSemantic(
            location=str(doc_item.get("location", "")),
            signature=signature,
            kind=kind,
            business_summary=business_summary,
            business_rules=business_rules,
            key_terms=key_terms,
        )

    def aggregate_file(self, file_rel: str, functions: list[FunctionSemantic], identity_card: dict[str, Any]) -> dict[str, Any]:
        self.clear_memory()
        self.add_to_memory(
            "system",
            "Summarize a file's functions into a file-level business summary. Return ONLY JSON with keys: file_summary, key_terms, workflows.",
        )
        self.add_to_memory(
            "user",
            f"File: {file_rel}\nDomain: {identity_card.get('domain','unknown')}\n\n"
            "Functions:\n"
            + "\n".join(f"- {f.signature}: {f.business_summary}" for f in functions)
            + "\n\nReturn ONLY JSON.",
        )
        obj = safe_json_loads(self.generate_response())
        if not isinstance(obj, dict):
            return {
                "file": file_rel,
                "file_summary": "(file summary unavailable)",
                "key_terms": [],
                "workflows": [],
            }
        return {
            "file": file_rel,
            "file_summary": str(obj.get("file_summary", "")) or "(no file summary)",
            "key_terms": [str(x) for x in (obj.get("key_terms") or [])],
            "workflows": [str(x) for x in (obj.get("workflows") or [])],
        }

    def aggregate_module(self, module_path: str, file_summaries: list[dict[str, Any]], identity_card: dict[str, Any]) -> dict[str, Any]:
        self.clear_memory()
        self.add_to_memory(
            "system",
            "Summarize a module/directory from its file summaries. Return ONLY JSON with keys: module_summary, responsibilities, key_terms.",
        )
        self.add_to_memory(
            "user",
            f"Module: {module_path}\nDomain: {identity_card.get('domain','unknown')}\n\n"
            "File summaries:\n"
            + "\n".join(f"- {fs['file']}: {fs['file_summary']}" for fs in file_summaries)
            + "\n\nReturn ONLY JSON.",
        )
        obj = safe_json_loads(self.generate_response())
        if not isinstance(obj, dict):
            return {
                "module": module_path,
                "module_summary": "(module summary unavailable)",
                "responsibilities": [],
                "key_terms": [],
            }
        return {
            "module": module_path,
            "module_summary": str(obj.get("module_summary", "")) or "(no module summary)",
            "responsibilities": [str(x) for x in (obj.get("responsibilities") or [])],
            "key_terms": [str(x) for x in (obj.get("key_terms") or [])],
        }

    def recursive_semantic_aggregation(
        self,
        doc_items: list[dict[str, Any]],
        *,
        repo_root: Path,
        identity_card: dict[str, Any],
        max_level: int = 3,
        max_workers: int = 8,
        batch_size: int = 50,
        cache_dir: Optional[Path] = None,
        show_progress: bool = True,
    ) -> dict[str, Any]:
        """Perform up to 3-level aggregation and persist intermediate results.

        Levels:
        1) function semantics
        2) file summary (aggregate functions)
        3) top-level module summary (aggregate files by top-level folder)
        """

        # --- Level 1: function semantics (prefilter + batching + parallelism) ---
        filtered = [it for it in doc_items if not self._is_trivial(it)]

        func_cache_path = None
        done_keys: set[str] = set()
        cached_function_items: list[dict[str, Any]] = []

        if cache_dir is not None:
            func_cache_path = cache_dir / "stage_b_function_items.jsonl"
            if func_cache_path.exists():
                # Resume from previous partial run
                with func_cache_path.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = __import__("json").loads(line)
                        except Exception:
                            continue
                        if isinstance(obj, dict):
                            cached_function_items.append(obj)
                            k = str(obj.get("location", "")) + "::" + str(obj.get("signature", ""))
                            done_keys.add(k)

        remaining: list[dict[str, Any]] = []
        for it in filtered:
            k = str(it.get("location", "")) + "::" + str(it.get("signature", ""))
            if k in done_keys:
                continue
            remaining.append(it)

        thread_local = threading.local()

        def worker_analyze(item: dict[str, Any]) -> dict[str, Any]:
            agent = getattr(thread_local, "agent", None)
            if agent is None:
                agent = AtomicAnalyzerAgent(config_path=self._config_path)
                thread_local.agent = agent
            sem = agent.analyze_doc_item(item, identity_card)
            return sem.__dict__

        new_items: list[dict[str, Any]] = []
        pbar = None
        if show_progress and tqdm is not None:
            pbar = tqdm(
                total=len(remaining),
                desc="Stage B1: docstrings → function semantics",
                unit="item",
            )
        if remaining:
            # Process in batches so we can persist progress periodically.
            step = max(1, int(batch_size))
            total_batches = (len(remaining) + step - 1) // step
            for batch_idx, i in enumerate(range(0, len(remaining), step), start=1):
                batch = remaining[i : i + step]
                if max_workers <= 1:
                    batch_results = []
                    for it in batch:
                        batch_results.append(worker_analyze(it))
                        if pbar is not None:
                            pbar.update(1)
                else:
                    batch_results = []
                    with ThreadPoolExecutor(max_workers=int(max_workers)) as ex:
                        futs = [ex.submit(worker_analyze, it) for it in batch]
                        for fut in as_completed(futs):
                            batch_results.append(fut.result())
                            if pbar is not None:
                                pbar.update(1)

                new_items.extend(batch_results)

                if pbar is None:
                    print(
                        f"[AtomicAnalyzer] batch {batch_idx}/{total_batches} done; "
                        f"new={len(batch_results)} cached={len(cached_function_items)} total={len(cached_function_items) + len(new_items)}"
                    )
                else:
                    pbar.set_postfix(
                        {
                            "batch": f"{batch_idx}/{total_batches}",
                            "cached": len(cached_function_items),
                            "total": len(cached_function_items) + len(new_items),
                        }
                    )

                if func_cache_path is not None:
                    with func_cache_path.open("a", encoding="utf-8") as f:
                        for obj in batch_results:
                            f.write(__import__("json").dumps(obj, ensure_ascii=False) + "\n")

        if pbar is not None:
            pbar.close()

        function_items: list[dict[str, Any]] = cached_function_items + new_items

        # If caller only wants level 1, stop here.
        if max_level <= 1:
            out = {
                "function_items": function_items,
                "file_summaries": {},
                "module_summaries": {},
            }
            return out

        # Group by file
        by_file: dict[str, list[dict[str, Any]]] = {}
        for f in function_items:
            loc = Path(str(f.get("location", "")))
            try:
                rel = str(loc.relative_to(repo_root))
            except Exception:
                rel = loc.name
            by_file.setdefault(rel, []).append(f)

        file_summaries: dict[str, dict[str, Any]] = {}
        file_cache_path = None
        if cache_dir is not None:
            file_cache_path = cache_dir / "stage_b_file_summaries.json"
            if file_cache_path.exists():
                try:
                    file_summaries = __import__("json").loads(file_cache_path.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    file_summaries = {}

        pending_files = [fr for fr in by_file.keys() if fr not in file_summaries]
        file_pbar = None
        if show_progress and tqdm is not None and pending_files:
            file_pbar = tqdm(total=len(pending_files), desc="Stage B2: functions → file summaries", unit="file")

        for file_rel, items in by_file.items():
            if file_rel in file_summaries:
                continue
            if file_pbar is not None:
                try:
                    file_pbar.set_description(f"Stage B2: {file_rel}")
                except Exception:
                    pass
            # Convert dict items to FunctionSemantic-like wrappers on the fly
            fn_objs: list[FunctionSemantic] = []
            for it in items:
                fn_objs.append(
                    FunctionSemantic(
                        location=str(it.get("location", "")),
                        signature=str(it.get("signature", "")),
                        kind=str(it.get("kind", "")),
                        business_summary=str(it.get("business_summary", "")),
                        business_rules=[str(x) for x in (it.get("business_rules") or [])],
                        key_terms=[str(x) for x in (it.get("key_terms") or [])],
                    )
                )
            file_summaries[file_rel] = self.aggregate_file(file_rel, fn_objs, identity_card)
            if file_cache_path is not None:
                file_cache_path.write_text(__import__("json").dumps(file_summaries, ensure_ascii=False, indent=2), encoding="utf-8")

            if file_pbar is not None:
                try:
                    file_pbar.update(1)
                except Exception:
                    pass

        if file_pbar is not None:
            file_pbar.close()

        # Optional progress for file/module aggregation (fast but can still be noticeable)
        # (We keep it minimal: only show a bar when tqdm is available.)

        if max_level <= 2:
            return {
                "function_items": function_items,
                "file_summaries": file_summaries,
                "module_summaries": {},
            }

        # --- Level 3: top-level module aggregation (depth capped) ---
        by_module: dict[str, list[dict[str, Any]]] = {}
        for file_rel, summary in file_summaries.items():
            p = Path(file_rel)
            if len(p.parts) <= 1:
                module = "(root)"
            else:
                module = p.parts[0]
            by_module.setdefault(module, []).append(summary)

        module_summaries: dict[str, dict[str, Any]] = {}
        module_cache_path = None
        if cache_dir is not None:
            module_cache_path = cache_dir / "stage_b_module_summaries.json"
            if module_cache_path.exists():
                try:
                    module_summaries = __import__("json").loads(module_cache_path.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    module_summaries = {}

        pending_modules = [m for m in by_module.keys() if m not in module_summaries]
        module_pbar = None
        if show_progress and tqdm is not None and pending_modules:
            module_pbar = tqdm(total=len(pending_modules), desc="Stage B3: files → module summaries", unit="module")

        for module, f_summaries in by_module.items():
            if module in module_summaries:
                continue
            if module_pbar is not None:
                try:
                    module_pbar.set_description(f"Stage B3: {module}")
                except Exception:
                    pass
            module_summaries[module] = self.aggregate_module(module, f_summaries, identity_card)
            if module_cache_path is not None:
                module_cache_path.write_text(__import__("json").dumps(module_summaries, ensure_ascii=False, indent=2), encoding="utf-8")

            if module_pbar is not None:
                try:
                    module_pbar.update(1)
                except Exception:
                    pass

        if module_pbar is not None:
            module_pbar.close()

        return {
            "function_items": function_items,
            "file_summaries": file_summaries,
            "module_summaries": module_summaries,
        }
