"""process_interactive hook: fast reaction to the realtime transcription.

Called right after a finished phrase has been transcribed by the
realtime (streaming) pass, BEFORE the batch (second) transcription:

- return a non-empty string: that text is sent to the phone immediately
  (text + speech) and the batch pass is skipped for this phrase;
- return an empty string (or None): the pipeline continues with the
  batch transcription biased by the domain vocabulary, as before.

Use it for commands, quick answers, or anything that should feel
instant and does not need the better accuracy of the batch pass.
"""

from __future__ import annotations


def process_interactive(
    realtime_text: str,
    client_id: str = "",
    domain: str = "",
    history: list[dict] | None = None,
) -> str:
    """React to the realtime transcription of a finished phrase.

    Return the text to send back immediately (skips the batch pass),
    or an empty string to let the pipeline continue with the batch
    transcription.

    `client_id` identifies the phone, `domain` is the detected
    vocabulary domain, and `history` is this client's history for that
    domain (list of {"role", "text", "domain"} records, oldest first).
    """
    return ""
