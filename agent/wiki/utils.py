from __future__ import annotations

import json
import re
import yaml
from pathlib import Path
from typing import Any, Iterable, Optional


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")
def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
def write_jsonl(path: Path, items: Iterable[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))
def read_jsonl(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def read_json_or_jsonl(path: Path) -> Any:
    """Read JSONL (list of objects) or JSON (any JSON value).

    This is used to support multiple intermediate data formats:
    - docstrings JSONL: one object per line
    - filtered components JSON: dict[component_id] -> component object
    """
    if path.suffix.lower() == ".jsonl":
        return read_jsonl(path)
    return read_json(path)


def safe_json_loads(text: str) -> Optional[Any]:
    text = str(text or "").strip()
    if not text:
        return None

    # Remove Markdown fences
    text = re.sub(r"^```(json)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()

    # Extract first JSON object if needed
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        text = m.group(0)

    try:
        return json.loads(text)
    except Exception:
        normalized = text.replace("'", '"')
        normalized = re.sub(r"\bTrue\b", "true", normalized)
        normalized = re.sub(r"\bFalse\b", "false", normalized)
        try:
            return json.loads(normalized)
        except Exception:
            return None


def strip_examples_section(doc: str) -> str:
    """Best-effort removal of Examples blocks in docstrings."""
    lines = doc.splitlines()
    out: list[str] = []
    in_examples = False
    fence = False

    for line in lines:
        if re.match(r"^\s*Examples?\s*:.*$", line):
            in_examples = True
            continue

        if in_examples:
            if line.strip().startswith("```"):
                fence = not fence
                continue
            if fence:
                continue
            # stop if a new section begins
            if re.match(r"^\s*(Args|Returns|Raises|Summary|Description|Parameters|Attributes)\s*:.*$", line):
                in_examples = False
                out.append(line)
            continue

        out.append(line)

    return "\n".join(out).strip()
def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
def md_link(text: str, target: str) -> str:
    return f"[{text}]({target})"


class DataPaths:
    """Holds paths for wiki pipeline. Reads repo/out settings from a
    `data_config.yaml` file supplied at construction (or defaults).

    Expected minimal keys in data_config.yaml:
      repo_dir: "data/raw_test_repo"
      readme_dir: "data/raw_test_repo/README.md"
      out_dir: "data/meta_test_repo"
    """

    def __init__(self, project_root: Path, data_config_path: Optional[Path] = None):
        self.project_root = project_root
        self.data_config_path = data_config_path or (project_root / "config" / "data_config.yaml")

        # Load config (be tolerant if missing)
        config = {}
        try:
            with open(self.data_config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            config = {}

        # repo_dir / readme_dir / out_dir are interpreted relative to project_root
        self.repo_dir = (project_root / config.get("repo_dir", "data/raw_test_repo")).resolve()
        self.readme_path = (project_root / config.get("readme_dir", "data/raw_test_repo/README.md")).resolve()
        self.out_dir = (project_root / config.get("out_dir", "data/meta_test_repo")).resolve()

        # default component/graph/tree filenames follow project conventions
        self.components_path = (self.out_dir / f"dependency_graph.json").resolve()
        self.dependency_graph_path = (self.out_dir / f"dependency_graph.json").resolve()
        self.tree_path = (self.out_dir / "repo_tree.json").resolve()
        self.repo_summary_path = (self.out_dir / "repo_summary.txt").resolve()

        # wiki output dir (under out_dir)
        self.output_dir = (self.out_dir / "repo_wiki").resolve()