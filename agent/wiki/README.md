# Recursive Wiki Agent System

This package implements a recursive, distributed Wiki builder for a repository.

## Pipeline
- Agent A: Context Manager (README -> context_tree + identity_card)
- Agent B: Atomic Analyzer (docstrings -> function semantics -> file summaries -> module summaries)
- Agent C: Architect (dependency graph + module summaries -> architecture_insights)
- Agent D: Wiki Builder (tree.json -> index + directory pages + file pages + link stitching)

## Run
From repo root:

- `python -m agent.wiki.build_repo_wiki`

Outputs Markdown pages to `repo_wiki/`.
