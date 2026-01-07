from typing import Optional
import tiktoken


def truncate_tokens(text: str, max_tokens: int) -> str:
    """
    Truncates text to a maximum of max_tokens.
    Strictly uses tiktoken for precise token counting.
    """
    if not text:
        return text
    if max_tokens is None or max_tokens <= 0:
        return ""

    # Verify tiktoken is available in the environment
    if 'tiktoken' not in globals() or tiktoken is None:
        raise RuntimeError(
            "tiktoken is required for truncation but is not available."
        )

    try:
        enc = tiktoken.get_encoding("cl100k_base")
        toks = enc.encode(text)
        if len(toks) <= max_tokens:
            return text
        toks = toks[:max_tokens]
        return enc.decode(toks)
    except Exception as e:
        # Raise error if tokenization cannot be completed as requested
        raise RuntimeError(f"Tokenization failed: {e}")


def get_agent_token_limits(agent: any) -> tuple[Optional[int], Optional[int]]:
    """
    Retrieve (max_input_tokens, max_output_tokens) from the agent.

    This implementation checks common locations used by the agents in this
    codebase: `agent.llm_params` (dict) and `agent.llm` (client wrapper).

    Returns a tuple (mit, mot) where either item may be None if missing.
    """
    mit = None
    mot = None

    # 1) Check agent.llm_params (dict) for either value
    try:
        lp = getattr(agent, "llm_params", None)
        if isinstance(lp, dict):
            v = lp.get("max_input_tokens")
            if isinstance(v, int):
                mit = v
            v = lp.get("max_output_tokens")
            if isinstance(v, int):
                mot = v
    except Exception:
        pass

    # 2) Check agent.llm object attributes (client wrapper) for missing values
    try:
        llm_obj = getattr(agent, "llm", None)
        if llm_obj is not None:
            if mit is None:
                v = getattr(llm_obj, "max_input_tokens", None)
                if isinstance(v, int):
                    mit = v
            if mot is None:
                v = getattr(llm_obj, "max_output_tokens", None)
                if isinstance(v, int):
                    mot = v
            # some wrappers store params dict on the client
            params = getattr(llm_obj, "params", None) or getattr(llm_obj, "kwargs", None)
            if isinstance(params, dict):
                if mit is None:
                    v = params.get("max_input_tokens") or params.get("max_tokens")
                    if isinstance(v, int):
                        mit = v
                if mot is None:
                    v = params.get("max_output_tokens") or params.get("output_tokens")
                    if isinstance(v, int):
                        mot = v
    except Exception:
        pass

    return mit, mot