from __future__ import annotations
from typing import Optional
from dataclasses import dataclass
from typing import Any, Optional
from tqdm import tqdm  
import tiktoken  

from ..rag import LocalRag
from ..utils import safe_json_loads
from ...base import BaseAgent
from ...utils import strip_think_blocks
from .utils import truncate_tokens, get_agent_token_limits


@dataclass
class ContextNode:
    title: str
    level: int
    raw: str
    summary: str
    children: list["ContextNode"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "level": self.level,
            "raw": self.raw,
            "summary": self.summary,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class IdentityCard:
    business_terms: dict[str, str]
    module_intents: list[str]
    domain: str
    goals: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "goals": self.goals,
            "business_terms": self.business_terms,
            "module_intents": self.module_intents,
        }


class ContextManagerAgent(BaseAgent):
    """Recursively summarize README into a context tree + identity card."""

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="context_manager", config_path=config_path)

    def recursive_readme_summary(self, readme: str, *, show_progress: bool = True) -> ContextNode:
        root = self._parse_markdown_headings(readme)

        # Count nodes that will actually trigger an LLM summary (nodes with non-empty raw, excluding root).
        nodes_to_summarize: list[ContextNode] = []

        def collect(n: ContextNode) -> None:
            if n.level > 0 and (n.raw or "").strip():
                nodes_to_summarize.append(n)
            for ch in n.children:
                collect(ch)

        collect(root)

        pbar = None
        if show_progress and tqdm is not None and len(nodes_to_summarize) > 0:
            pbar = tqdm(total=len(nodes_to_summarize), desc="Stage A: README → context tree", unit="section")

        try:
            self._summarize_node(root, parent_context="", pbar=pbar)
        finally:
            if pbar is not None:
                pbar.close()
        return root

    def build_identity_card(self, context_tree: ContextNode) -> IdentityCard:
        self.clear_memory()
        self.add_to_memory(
            "system",
            "You are a Context Manager agent. From the README summaries, extract a business terminology glossary and module intent list. "
            "Return ONLY JSON with keys: domain, goals, business_terms (object), module_intents (list).",
        )
        self.add_to_memory(
            "user",
            "README summary tree (flattened):\n" + self._flatten_summaries(context_tree) + "\n\nReturn ONLY JSON.",
        )
        raw = strip_think_blocks(self.generate_response() or "")
        obj = safe_json_loads(raw)
        if not isinstance(obj, dict):
            return IdentityCard(business_terms={}, module_intents=[], domain="unknown", goals=[])

        terms = obj.get("business_terms") or {}
        if not isinstance(terms, dict):
            terms = {}

        return IdentityCard(
            domain=str(obj.get("domain", "unknown")),
            goals=[str(x) for x in (obj.get("goals") or [])],
            business_terms={str(k): str(v) for k, v in terms.items()},
            module_intents=[str(x) for x in (obj.get("module_intents") or [])],
        )

    def process(self, readme_content: str, *, show_progress: bool = True) -> dict[str, Any]:
        tree = self.recursive_readme_summary(readme_content, show_progress=show_progress)
        identity = self.build_identity_card(tree)
        return {
            "context_tree": tree.to_dict(),
            "identity_card": identity.to_dict(),
        }

    # ---------------- internals ----------------

    def _parse_markdown_headings(self, text: str) -> ContextNode:
        lines = text.splitlines()
        root = ContextNode(title="README", level=0, raw="", summary="", children=[])
        stack: list[ContextNode] = [root]

        def flush_to(node: ContextNode, buf: list[str]) -> None:
            chunk = "\n".join(buf).strip()
            if chunk:
                node.raw = (node.raw + "\n" + chunk).strip() if node.raw else chunk

        buf: list[str] = []
        for line in lines:
            m = __import__("re").match(r"^(#{1,6})\s+(.*)$", line)
            if not m:
                buf.append(line)
                continue

            # heading
            flush_to(stack[-1], buf)
            buf = []
            level = len(m.group(1))
            title = m.group(2).strip()
            node = ContextNode(title=title, level=level, raw="", summary="", children=[])

            while stack and stack[-1].level >= level:
                stack.pop()
            stack[-1].children.append(node)
            stack.append(node)

        flush_to(stack[-1], buf)
        return root

    def _summarize_node(self, node: ContextNode, *, parent_context: str, pbar=None) -> None:
        raw = (node.raw or "").strip()

        if raw:
            # Map-reduce style when content is long
            rag = LocalRag(device="cpu", chunk_size=1200, overlap=150)
            rag.add_text(raw, source=node.title)
            rag.build()

            queries = [
                "business purpose",
                "core entities",
                "workflow",
                "rules and constraints",
            ]
            retrieved = "\n\n".join(
                f"## {q}\n" + "\n\n".join(h.text for h in rag.query(q, k=2)) for q in queries
            )

            # Compute token budgets from agent config (strict; no fallback)
            max_input_tokens, max_output_tokens = get_agent_token_limits(self)
            if not isinstance(max_input_tokens, int) or not isinstance(max_output_tokens, int):
                raise RuntimeError(
                    "Agent token limits not found. `get_agent_token_limits` must return "
                    "(max_input_tokens:int, max_output_tokens:int). Install/configure tiktoken and set token limits in agent config."
                )
            
            # Reserve some tokens for prompt overhead and expected output
            reserve = int(max_output_tokens * 0.5) + 128
            input_budget = max(256, max_input_tokens - reserve)
            # Split input budget among parent_context / retrieved / raw
            parent_budget = max(32, int(input_budget * 0.12))
            retrieved_budget = max(128, int(input_budget * 0.44))
            raw_budget = max(128, int(input_budget - parent_budget - retrieved_budget))
            
            # Truncate by tokens using the shared `truncate_tokens` util.
            # Note: `truncate_tokens` will raise if `tiktoken` is missing.
            parent_context = truncate_tokens(parent_context or "", parent_budget)
            retrieved = truncate_tokens(retrieved or "", retrieved_budget)
            raw = truncate_tokens(raw or "", raw_budget)

            self.clear_memory()
            self.add_to_memory(
                "system",
                "Summarize this README section for business context. Output 4-8 bullet points, concise. Do NOT include <think> blocks.",
            )
            self.add_to_memory(
                "user",
                f"Parent context summary:\n{parent_context}\n\nSection: {node.title}\n\nRetrieved:\n{retrieved}\n\nRaw:\n{raw}",
            )
            if pbar is not None:
                try:
                    pbar.set_description(f"Stage A: {node.title[:60]}")
                except Exception:
                    pass
            node.summary = strip_think_blocks(self.generate_response() or "").strip()
            if pbar is not None:
                try:
                    pbar.update(1)
                except Exception:
                    pass
        else:
            node.summary = parent_context.strip()

        new_parent = (node.summary or parent_context).strip()
        for c in node.children:
            self._summarize_node(c, parent_context=new_parent, pbar=pbar)

    def _flatten_summaries(self, node: ContextNode) -> str:
        lines: list[str] = []

        def walk(n: ContextNode):
            indent = "  " * max(0, n.level - 1)
            if n.title and n.level > 0:
                lines.append(f"{indent}- {n.title}: {n.summary}")
            for ch in n.children:
                walk(ch)

        walk(node)
        return "\n".join(lines)
