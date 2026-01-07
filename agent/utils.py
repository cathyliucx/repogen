import re


def strip_think_blocks(text: str) -> str:
    """Remove model reasoning blocks like <think>...</think> from output."""
    if not text:
        return text
    # Remove one or more <think> blocks anywhere in the response.
    cleaned = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.lstrip()


