"""process_interactive hook: fast reaction to the realtime transcription.

Called right after a finished phrase has been transcribed by the
realtime (streaming) pass, BEFORE the batch (second) transcription:

- return a non-empty string: that text is sent to the phone immediately
  (text + speech) and the batch pass is skipped for this phrase;
- return an empty string (or None): the pipeline continues with the
  batch transcription biased by the domain vocabulary, as before.

Menu commands: the phone app's command menu is built from
static/commands.json (theme > sub-theme > command). When the spoken
phrase matches a menu command, the matching handler in HANDLERS is
called with the three menu levels (theme, sub_theme, command). A
handler returns the text to send back ("Fait" by default).

To add a treatment for a new command: add the command to
static/commands.json, then add an entry to HANDLERS below:

    "Rédémarre le service": restart_service,

with:

    def restart_service(theme, sub_theme, command):
        ...do the work...
        return "Service redémarré."

Any command without a handler falls back to handle_default, which
just acknowledges ("Fait"). No other code change is needed.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("phone-stream.interactive")

ROOT = Path(__file__).resolve().parent
COMMANDS_FILE = ROOT / "static" / "commands.json"

DEFAULT_REPLY = "Fait"


def _normalize(text: str) -> str:
    """Loose normalization for matching spoken text to menu entries:
    lowercase, accents and punctuation removed, spaces collapsed."""
    text = text.lower().strip()
    text = re.sub(r"[!?.,;:«»\"'()]", " ", text)
    text = re.sub(r"[éèêë]", "e", text)
    text = re.sub(r"[àâä]", "a", text)
    text = re.sub(r"[îï]", "i", text)
    text = re.sub(r"[ôö]", "o", text)
    text = re.sub(r"[ûüù]", "u", text)
    text = re.sub(r"ç", "c", text)
    return re.sub(r"\s+", " ", text).strip()


def _load_menu_commands() -> dict[str, tuple[str, str, str]]:
    """Index the menu commands: normalized text -> (theme, sub, command)."""
    index: dict[str, tuple[str, str, str]] = {}
    if not COMMANDS_FILE.is_file():
        log.warning("menu commands file missing: %s", COMMANDS_FILE)
        return index
    try:
        tree = json.loads(COMMANDS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.error("cannot read %s: %s", COMMANDS_FILE, exc)
        return index
    for theme, sub_topics in tree.items():
        if not isinstance(sub_topics, dict):
            continue
        for sub_theme, commands in sub_topics.items():
            if not isinstance(commands, list):
                continue
            for command in commands:
                index[_normalize(command)] = (theme, sub_theme, command)
    return index


MENU_COMMANDS = _load_menu_commands()


# ----------------------------------------------------------------------
# Handlers for menu commands. Add one entry per command to customize
# its treatment; unlisted commands fall back to handle_default ("Fait").
# ----------------------------------------------------------------------


def handle_default(theme: str, sub_theme: str, command: str) -> str:
    """Default treatment: acknowledge the command."""
    return DEFAULT_REPLY


HANDLERS: dict = {
    # "État du serveur": server_status,   <- add custom treatments here
}


def run_menu_command(theme: str, sub_theme: str, command: str) -> str:
    """Dispatch a recognized menu command to its handler."""
    handler = HANDLERS.get(command, handle_default)
    try:
        return handler(theme, sub_theme, command) or DEFAULT_REPLY
    except Exception as exc:
        log.error("handler for %r failed: %s", command, exc)
        return DEFAULT_REPLY


def match_menu_command(text: str) -> tuple[str, str, str] | None:
    """Return (theme, sub_theme, command) if the text is a menu command."""
    return MENU_COMMANDS.get(_normalize(text))


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
    # Menu commands: match the spoken phrase against the phone app's
    # command menu (same source: static/commands.json).
    match = match_menu_command(realtime_text)
    if match is not None:
        theme, sub_theme, command = match
        log.info("menu command: %s > %s > %s", theme, sub_theme, command)
        return run_menu_command(theme, sub_theme, command)
    return ""
