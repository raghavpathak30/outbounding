"""
Defensive plain text extraction helper for LLM response objects across LangChain and Google GenAI.
Safely extracts text from strings, content block lists, and .text accessors, skipping
reasoning/thinking blocks, tool calls, and thought signature extras.
"""
from typing import Any, Optional


def extract_llm_text(response: Any) -> Optional[str]:
    """
    Extracts plain text from a LangChain or Google GenAI response object or raw content block.

    Defensively handles:
    1. Message object exposing .text (property or method in langchain-core 1.x / google-genai).
    2. String content (e.g. response.content == "..." or response == "...").
    3. List of content blocks (dicts or objects):
       - Extracts the text field for every block where type == "text".
       - Joins extracted blocks with newlines.
       - Explicitly skips non-text blocks (thinking, reasoning, tool calls).
       - Never includes anything from 'extras' (guarantees thought signatures are discarded).
    4. Empty or whitespace-only extraction yields None, allowing callers to fall back to offline templates.

    Args:
        response: Any LangChain BaseMessage (e.g. AIMessage), google.genai response,
                  list of content blocks, dict, or string.

    Returns:
        Cleaned plain text string, or None if no valid text could be extracted.
    """
    if response is None:
        return None

    # Shape 1: Message object exposing .text (property or callable method in langchain-core 1.x / google-genai)
    text_prop = getattr(response, "text", None)
    if text_prop is not None:
        if isinstance(text_prop, str) and text_prop.strip():
            return text_prop.strip()
        if callable(text_prop):
            try:
                res = text_prop()
                if isinstance(res, str) and res.strip():
                    return res.strip()
            except Exception:
                pass

    # Shape 2 & 3: Examine content attribute or response itself
    content = getattr(response, "content", response)

    # 2. Content is a plain string
    if isinstance(content, str):
        cleaned = content.strip()
        return cleaned if cleaned else None

    # 3. Content is a list of blocks
    if isinstance(content, list):
        text_parts = []
        for block in content:
            b_type = None
            b_text = None

            if isinstance(block, dict):
                b_type = block.get("type")
                b_text = block.get("text")
            elif isinstance(block, str):
                b_type = "text"
                b_text = block
            elif isinstance(block, object):
                b_type = getattr(block, "type", None)
                b_text = getattr(block, "text", None)

            # Explicitly skip non-text blocks (thinking, reasoning, tool_calls, etc.)
            # Never include anything from 'extras' (thought signatures, metadata)
            if b_type == "text" and isinstance(b_text, str) and b_text.strip():
                text_parts.append(b_text.strip())

        if text_parts:
            joined = "\n".join(text_parts).strip()
            return joined if joined else None

    # 4. Content is a single block dict or object
    if isinstance(content, dict):
        b_type = content.get("type", "text")
        b_text = content.get("text")
        if b_type == "text" and isinstance(b_text, str) and b_text.strip():
            return b_text.strip()

    if hasattr(content, "type") and hasattr(content, "text"):
        if getattr(content, "type") == "text":
            t = getattr(content, "text")
            if isinstance(t, str) and t.strip():
                return t.strip()

    return None
