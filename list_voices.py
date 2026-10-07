#!/usr/bin/env python3
"""List the TTS voice ids available on your Mistral account.

Usage:
    export MISTRAL_API_KEY=...     (Windows: set MISTRAL_API_KEY=...)
    python list_voices.py

Then pick a voice id and either:
    - export MISTRAL_TTS_VOICE=<voice-id>   before starting the server, or
    - edit TTS_VOICE in speech_pipeline.py
"""

import os
import sys

from mistralai.client import Mistral


def main() -> None:
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        sys.exit("MISTRAL_API_KEY is not set.")

    client = Mistral(api_key=api_key)
    response = client.audio.voices.list(type_="all", limit=100)
    voices = getattr(response, "voices", None) or []
    if not voices:
        print("No voices found on this account.")
        return
    for voice in voices:
        vid = getattr(voice, "id", None) or getattr(voice, "voice_id", "?")
        name = getattr(voice, "name", "?")
        langs = ", ".join(getattr(voice, "languages", []) or [])
        print(f"{vid}  name={name}  languages={langs}")


if __name__ == "__main__":
    main()
