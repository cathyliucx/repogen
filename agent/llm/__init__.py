"""LLM backends.

Keep this module lightweight: optional provider SDKs (Anthropic/Google, etc.)
should not be imported unless the corresponding backend is actually used.
"""

from .base import BaseLLM

__all__ = [
    "BaseLLM",
    "OpenAILLM",
    "ClaudeLLM",
    "HuggingFaceLLM",
    "GeminiLLM",
    "LLMFactory",
]


def __getattr__(name: str):
    if name == "OpenAILLM":
        from .openai_llm import OpenAILLM

        return OpenAILLM
    if name == "ClaudeLLM":
        from .claude_llm import ClaudeLLM

        return ClaudeLLM
    if name == "HuggingFaceLLM":
        from .huggingface_llm import HuggingFaceLLM

        return HuggingFaceLLM
    if name == "GeminiLLM":
        from .gemini_llm import GeminiLLM

        return GeminiLLM
    if name == "LLMFactory":
        from .factory import LLMFactory

        return LLMFactory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")