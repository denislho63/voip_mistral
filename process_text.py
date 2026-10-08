"""
processText hook: decide what to say and display from the transcriptions.

Receives both transcriptions of each finished phrase — the realtime one and
the batch one (biased with the custom vocabulary) — and returns the text to
send back to the phone (as text and as speech).

Customize this function to plug in an LLM, a translator, a command
interpreter, etc. Return an empty string to say nothing.
"""

from __future__ import annotations


def processText(
    realtime_text: str,
    batch_text: str,
    client_id: str = "",
    domain: str = "",
    history: list[dict] | None = None,
) -> str:
    """Return the text to speak and display for a finished phrase.

    Default behavior: prefer the batch transcription (custom vocabulary),
    falling back to the realtime one when the batch pass failed.

    `client_id` identifies the connected phone, `domain` is the detected
    vocabulary domain of the phrase, and `history` is the client's
    history for that domain (list of {"role", "text", "domain"}
    records, oldest first) — context to build smarter responses.
    """
    return batch_text or realtime_text
