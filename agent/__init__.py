"""RepoGen agent package.

This module defines the public import surface for the `agent` package.

Goal:
- Let callers do `from agent import BaseAgent, MetaReader`.
- Avoid importing heavy/optional dependencies at import-time.

Note:
Some agent modules may rely on optional provider SDKs or local services.
We keep imports here lightweight and resilient.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
# Base types are safe to import.
from .base import BaseAgent
# Utilities are safe to import.
from .utils import strip_think_blocks


__all__ = [
	"BaseAgent",
	"strip_think_blocks",
]
