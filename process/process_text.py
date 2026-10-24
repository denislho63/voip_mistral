"""
processText hook: decide what to say and display from the transcriptions.

Receives both transcriptions of each finished phrase — the realtime one and
the batch one (biased with the custom vocabulary) — and returns the text to
send back to the phone (as text and as speech).

Processing order:
1. Try domain-specific processing via process_domain()
2. If domain processor returns empty, try AI processing via process_ai() (if enabled)
3. If both return empty, fall back to the batch/real-time transcription

This allows for custom responses per domain while maintaining the AI fallback
for generic questions.

Customize this function to plug in an LLM, a translator, a command
interpreter, etc. Return an empty string to say nothing.
"""

from __future__ import annotations

import os

# Configuration: enable/disable AI processing
USE_AI = os.environ.get("PHONE_STREAM_USE_AI", "true").lower() in ("true", "1", "yes")


def processText(
    realtime_text: str,
    batch_text: str,
    client_id: str = "",
    domain: str = "",
    history: list[dict] | None = None,
) -> str:
    """Return the text to speak and display for a finished phrase.

    Processing order:
    1. Try domain-specific processing via process_domain()
    2. If empty, try AI processing via process_ai() (if USE_AI=true)
    3. If both empty, return the transcription

    This allows for custom, deterministic responses for specific domains
    (e.g., "Qu'est-ce qu'une API?" -> predefined answer) while using AI
    for more generic questions.

    The AI processing generates concise responses with:
    - Numbered lists for easy voice navigation
    - Clear voice-friendly keywords (D'abord, Ensuite, Enfin, etc.)
    - Short, direct sentences suitable for speech synthesis

    `client_id` identifies the connected phone, `domain` is the detected
    vocabulary domain of the phrase, and `history` is the client's
    history for that domain (list of {"role", "text", "domain"}
    records, oldest first) — context to build smarter responses.
    """
    # Use the batch transcription as the base text
    text = batch_text or realtime_text
    
    if not text:
        return ""
    
    # 1. Try domain-specific processing
    try:
        from .process_domain import process_domain
        domain_response = process_domain(
            realtime_text=realtime_text,
            batch_text=batch_text,
            client_id=client_id,
            domain=domain,
            history=history,
        )
        if domain_response:
            return domain_response
    except Exception:
        # If domain processing fails, continue to AI fallback
        pass
    
    # 2. Try AI processing (if enabled)
    if USE_AI:
        try:
            from .process_ai import process_ai
            ai_response = process_ai(
                realtime_text=realtime_text,
                batch_text=batch_text,
                client_id=client_id,
                domain=domain,
                history=history,
            )
            if ai_response:
                return ai_response
        except Exception:
            # If AI processing fails, continue to fallback
            pass
    
    # 3. Fallback: return the transcription
    return text
