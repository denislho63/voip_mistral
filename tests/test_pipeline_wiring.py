"""Regression test: the pipeline callbacks must match the hook signatures.

A previous refactor changed sendTextBlock/sendAudioBlock to take a
ClientSession instead of a ServerConnection, but the closures wired in
start_pipeline() still passed the raw connection - crashing the
realtime stream with "'ServerConnection' object has no attribute
'connection'" as soon as the pipeline produced text or audio.

This test builds a real pipeline via start_pipeline() with a mocked
Mistral client, then invokes the captured on_text/on_audio callbacks and
asserts the data actually reaches the (mocked) websocket. It requires
mistralai to be importable, hence the skipif.
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")

import server
from speech_pipeline import MISTRAL_AVAILABLE

pytestmark = pytest.mark.skipif(not MISTRAL_AVAILABLE, reason="mistralai not installed")


class FakeConnection:
    """Minimal ServerConnection double: records what the server sends."""

    def __init__(self):
        self.remote_address = ("127.0.0.1", 12345)
        self.sent: list = []

    async def send(self, data):
        self.sent.append(data if isinstance(data, bytes) else data.encode())


class FakePipeline:
    """Stands in for SpeechPipeline; captures the callbacks."""

    def __init__(self, on_text, on_audio):
        self.on_text = on_text
        self.on_audio = on_audio


async def test_pipeline_callbacks_reach_client(monkeypatch):
    conn = FakeConnection()

    def fake_speech_pipeline(on_text, on_audio, client_id="", history=None):
        return FakePipeline(on_text, on_audio)

    monkeypatch.setattr(server, "pipeline_available", lambda: True)
    monkeypatch.setattr(server, "SpeechPipeline", fake_speech_pipeline)

    session = server.ClientSession(
        connection=conn, client_id="test-client", history=None
    )
    await server.start_pipeline(session)
    assert session.pipeline is not None

    # Simulate the realtime pipeline delivering text and audio:
    # this is the exact path that crashed with AttributeError before.
    await session.pipeline.on_text("bonjour", "transcription")
    await session.pipeline.on_audio(b"\x00\x00")

    assert len(conn.sent) == 2
    assert b'"text": "bonjour"' in conn.sent[0]
    assert conn.sent[1] == b"\x00\x00"


async def test_stop_pipeline_without_pipeline():
    conn = FakeConnection()
    session = server.ClientSession(connection=conn)
    await server.stop_pipeline(session)  # must not raise


async def test_real_pipeline_signature_accepts_context():
    """Regression test: SpeechPipeline.__init__ must accept client_id and
    history (the server passes them; a signature drift crashed it with
    "unexpected keyword argument 'client_id'").
    """
    import inspect

    import speech_pipeline

    params = set(inspect.signature(speech_pipeline.SpeechPipeline.__init__).parameters)
    assert {"client_id", "history"} <= params
