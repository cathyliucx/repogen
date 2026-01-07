"""Minimal offline test for ReadmeFilterAgent.

Goals:
- Use local fixture repo under data/raw_test_repo
- Instantiate ReadmeFilterAgent with config/agent_config.yaml
- Avoid any real LLM/network calls by monkeypatching generate_response

Run:
  python scripts/test/z_readme_filter_agent_minimal_test.py
"""

from __future__ import annotations
from pathlib import Path
import sys


def main() -> None:
    from agent.readmefilter import ReadmeFilterAgent

    config_path = Path("config") / "agent_config.yaml"
    readme_path = Path("data") / "raw_test_repo" / "README.md" 
    assert config_path.exists(), f"Missing config: {config_path}"
    assert readme_path.exists(), f"Missing README fixture: {readme_path}"

    readme_text = readme_path.read_text(encoding="utf-8", errors="replace")
    assert len(readme_text) > 50, "README fixture looks unexpectedly short"
    # print('readme_text:', readme_text)
    agent = ReadmeFilterAgent(config_path=str(config_path))
    
    result = agent.process(readme_text)
    print(f"LLM Response: {result}")

if __name__ == "__main__":
    main()
