"""
process_command hook: handle text typed by the user in the phone app.

The text the user sends from the app is routed here. The function returns
the text to send back to the phone: it is delivered as text (displayed,
copyable) and, when it can be synthesized, as audio to the headset.

For now it simply returns the received text, which the server converts to
speech. Customize it to plug in an LLM, a command interpreter, a
translator, etc. Return an empty string to send nothing back.
"""

from __future__ import annotations


def process_command(text: str) -> str:
    """Return the response text for a user-typed message.

    Current behavior: echo the received text (the server speaks it back
    via text-to-speech and displays it).
    """
    return text
