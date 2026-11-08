"""Extract plain text from a Mistral chat message, across SDK generations.

mistralai >= 3 returns `message.content` as a list of content chunks
(e.g. [TextChunk(type='text', text='...')]) instead of a plain string.
Older SDK versions returned a plain `str`. This helper normalizes both
forms to a single string.
"""

from __future__ import annotations

import logging

log = logging.getLogger("phone-stream.mistral_content")


def _chunk_text(chunk) -> str:
    """Return the text of a single content chunk (model object or dict)."""
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, dict):
        return str(chunk.get("text") or "")
    text = getattr(chunk, "text", None)
    if text is not None:
        return str(text)
    return ""


def message_text(message) -> str:
    """Return the text content of a chat message as a plain string.

    Handles:
    - content as str (old SDK)
    - content as list of chunks: TextChunk models, dicts, or raw strings
    - content as None
    """
    content = getattr(message, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "".join(_chunk_text(chunk) for chunk in content)
    # Single chunk object or unexpected type
    text = _chunk_text(content)
    if not text:
        log.warning("unrecognized message content type: %s", type(content))
    return text
