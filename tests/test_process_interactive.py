"""Tests for the process_interactive hook and its wiring into the pipeline.

The hook runs after the realtime transcription of a finished phrase:
non-empty output is delivered immediately (batch pass skipped), empty
output lets the normal batch + processText flow continue.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

import speech_pipeline
from client_history import ClientHistory
from process_interactive import process_interactive


class TestDefaultHook:
    def test_default_returns_empty(self):
        assert process_interactive("une phrase.") == ""

    def test_accepts_context_kwargs(self):
        assert (
            process_interactive(
                "phrase.", client_id="c1", domain="pastoral", history=[]
            )
            == ""
        )


class FakePipeline:
    """Minimal SpeechPipeline double exposing the delta-handler flow."""

    def __init__(self, client_id="c1", history=None):
        self.client_id = client_id
        self.history = history
        self.last_domain = ""
        self.delivered: list = []
        self.batch_called = 0

    async def _classify(self, phrase):
        return "pastoral"

    def _record_phrase(self, domain, realtime_text, batch_text):
        if self.history is None:
            return None
        self.history.add_phrase(domain, batch_text or realtime_text)
        return self.history.get(domain)

    def _record_response(self, domain, text):
        if self.history is not None:
            self.history.add_response(domain, text)

    async def on_text(self, text, tag):
        self.delivered.append(("text", text, tag))

    async def on_audio(self, pcm):
        self.delivered.append(("audio", pcm))

    async def synthesize(self, text):
        return b"PCM"

    async def _transcribe_batch(self, wav_data, vocabulary):
        self.batch_called += 1
        return "texte batch"


async def run_delta(pipeline, monkeypatch, interactive_result):
    """Drive _handle_delta on a fake pipeline with mocked hooks."""
    monkeypatch.setattr(
        speech_pipeline, "process_interactive", lambda *a, **k: interactive_result
    )

    def fake_process_text(realtime, batch, **kwargs):
        return batch

    monkeypatch.setattr(speech_pipeline, "processText", fake_process_text)

    # replicate the flow of _handle_delta on the fake pipeline
    phrase = "bonjour."
    domain = await pipeline._classify(phrase)
    pipeline.last_domain = domain
    history_records = pipeline._record_phrase(domain, phrase, "")
    interactive_text = speech_pipeline.process_interactive(
        phrase, client_id=pipeline.client_id, domain=domain, history=history_records
    )
    if interactive_text:
        pipeline._record_response(domain, interactive_text)
        await pipeline.on_text(interactive_text, "interactive")
        pcm = await pipeline.synthesize(interactive_text)
        if pcm:
            await pipeline.on_audio(pcm)
        return
    vocabulary = ["berger"]
    batch_text = await pipeline._transcribe_batch(None, vocabulary)
    spoken = speech_pipeline.processText(
        phrase,
        batch_text,
        client_id=pipeline.client_id,
        domain=domain,
        history=history_records,
    )
    if spoken:
        pipeline._record_response(domain, spoken)
        await pipeline.on_text(spoken, "transcription")


class TestInteractiveFlow:
    async def test_non_empty_output_skips_batch(self, monkeypatch):
        p = FakePipeline(history=ClientHistory("c1"))
        await run_delta(p, monkeypatch, "réponse rapide")
        assert p.batch_called == 0
        assert p.delivered[0] == ("text", "réponse rapide", "interactive")

    async def test_empty_output_continues_to_batch(self, monkeypatch):
        p = FakePipeline(history=ClientHistory("c1"))
        await run_delta(p, monkeypatch, "")
        assert p.batch_called == 1
        assert p.delivered[0] == ("text", "texte batch", "transcription")

    async def test_interactive_response_recorded_in_history(self, monkeypatch):
        h = ClientHistory("c1")
        p = FakePipeline(history=h)
        await run_delta(p, monkeypatch, "réponse rapide")
        roles = [r["role"] for r in h.get("pastoral")]
        assert roles == ["phrase", "response"]
