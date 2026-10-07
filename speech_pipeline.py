"""
Realtime speech-to-text pipeline for the phone-stream server.

Bridges the WebSocket phone client to the Mistral realtime transcription
API, with the double-transcription strategy: each phrase is transcribed
live (streaming), then re-transcribed in batch with a custom vocabulary
(context bias) for better quality on domain-specific terms.

Requires:
    pip install mistralai
    export MISTRAL_API_KEY=...   (Windows: set MISTRAL_API_KEY=...)

If mistralai is not installed or MISTRAL_API_KEY is not set, the pipeline
is disabled and the server keeps running (audio is dropped with a warning).
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import struct
import wave
from typing import AsyncIterator, Awaitable, Callable

from process_text import processText

log = logging.getLogger("phone-stream.speech")

try:
    from mistralai.client import Mistral
    from mistralai.client.models import (
        AudioFormat,
        File,
        RealtimeTranscriptionError,
        RealtimeTranscriptionSessionCreated,
        TranscriptionStreamDone,
        TranscriptionStreamTextDelta,
    )

    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False

REALTIME_MODEL = "voxtral-mini-transcribe-realtime-2602"
BATCH_MODEL = "voxtral-mini-latest"
TTS_MODEL = "voxtral-mini-tts-2603"
TTS_SAMPLE_RATE = 24000  # native output rate of the TTS API (pcm)
TTS_VOICE = os.environ.get("MISTRAL_TTS_VOICE", "neutral_female")
SAMPLE_RATE = 16000
LANGUAGE = "fr"

# Custom vocabulary applied to the batch (second) transcription pass.
CUSTOM_VOCABULARY = [
    "AIForMe",
    "Lhospitalier",
    "acronyme",
    "Marthuret",
]

OnText = Callable[[str, str], Awaitable[None]]
OnAudio = Callable[[bytes], Awaitable[None]]


def _extract_tts_audio(response) -> bytes:
    """Extract raw audio bytes from a TTS response, across SDK versions."""
    for attr in ("audio", "audio_data", "data", "content"):
        value = getattr(response, attr, None)
        if not value:
            continue
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            import base64
            try:
                return base64.b64decode(value)
            except Exception:
                return value.encode()
    return b""


def _resample_pcm_s16le(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linearly resample 16-bit mono PCM between rates (stdlib only)."""
    if not pcm or src_rate == dst_rate:
        return pcm
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm[: len(pcm) // 2 * 2])
    n_src = len(samples)
    if n_src == 0:
        return b""
    n_dst = int(n_src * dst_rate / src_rate)
    out = bytearray()
    for i in range(n_dst):
        pos = i * (n_src - 1) / max(n_dst - 1, 1)
        i0 = int(pos)
        i1 = min(i0 + 1, n_src - 1)
        frac = pos - i0
        out += int(samples[i0] * (1 - frac) + samples[i1] * frac).to_bytes(2, "little", signed=True)
    return bytes(out)


def pipeline_available() -> bool:
    """True if the Mistral pipeline can run (library + API key present)."""
    return MISTRAL_AVAILABLE and bool(os.environ.get("MISTRAL_API_KEY"))


def _convert_tts_to_pcm_s16le(raw: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Convert TTS raw audio (float32 LE) to 16-bit PCM and resample.

    The /v1/audio/speech endpoint returns raw float32 LE samples with the
    "pcm" response format; the headset expects 16-bit PCM at SAMPLE_RATE.
    """
    n = len(raw) // 4
    if n == 0:
        return b""
    floats = struct.unpack(f"<{n}f", raw[: n * 4])
    n_dst = int(n * dst_rate / src_rate)
    out = bytearray()
    for i in range(n_dst):
        pos = i * (n - 1) / max(n_dst - 1, 1)
        i0 = int(pos)
        i1 = min(i0 + 1, n - 1)
        frac = pos - i0
        value = floats[i0] * (1 - frac) + floats[i1] * frac
        clamped = max(-1.0, min(1.0, value))
        out += int(clamped * 32767).to_bytes(2, "little", signed=True)
    return bytes(out)


def tts_pcm(client, text: str) -> bytes:
    """Synthesize text to speech (blocking) via /v1/audio/speech.

    Returns 16-bit mono PCM at SAMPLE_RATE (16 kHz), or b"" on failure.
    """
    try:
        response = client.audio.speech.complete(
            model=TTS_MODEL,
            input=text,
            voice_id=TTS_VOICE,
            response_format="pcm",
        )
        raw = _extract_tts_audio(response)
    except Exception as exc:
        log.error("text-to-speech failed: %s", exc)
        return b""
    if not raw:
        return b""
    return _convert_tts_to_pcm_s16le(raw, TTS_SAMPLE_RATE, SAMPLE_RATE)


class SpeechPipeline:
    """One realtime transcription session per WebSocket client.

    PCM chunks from the phone microphone are fed via feed(); the realtime
    model streams text deltas; when a phrase ends ('.', '!', '?') the phrase
    audio is re-transcribed in batch with the custom vocabulary and the
    (better) batch text is delivered via on_text().
    """

    def __init__(self, on_text: OnText, on_audio: OnAudio):
        api_key = os.environ["MISTRAL_API_KEY"]
        self.client = Mistral(api_key=api_key)
        self.audio_format = AudioFormat(encoding="pcm_s16le", sample_rate=SAMPLE_RATE)
        self.on_text = on_text
        self.on_audio = on_audio
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.audio = io.BytesIO()
        self.phrase = ""
        self.task: asyncio.Task | None = asyncio.create_task(self._run())

    async def feed(self, pcm: bytes) -> None:
        """Accept one PCM block (16-bit mono 16 kHz) from the microphone."""
        self.audio.write(pcm)
        await self.queue.put(pcm)

    async def synthesize(self, text: str) -> bytes:
        """Convert text to headset-ready PCM (non-blocking wrapper)."""
        return await asyncio.to_thread(tts_pcm, self.client, text)

    async def stop(self) -> None:
        """End the session and wait for the background task to finish."""
        await self.queue.put(None)
        if self.task:
            try:
                await self.task
            except Exception:
                pass
        self.task = None

    async def _stream(self) -> AsyncIterator[bytes]:
        while True:
            chunk = await self.queue.get()
            if chunk is None:
                return
            yield chunk

    async def _run(self) -> None:
        try:
            async for event in self.client.audio.realtime.transcribe_stream(
                audio_stream=self._stream(),
                model=REALTIME_MODEL,
                audio_format=self.audio_format,
            ):
                if isinstance(event, RealtimeTranscriptionSessionCreated):
                    log.info("realtime transcription session created")
                elif isinstance(event, TranscriptionStreamTextDelta):
                    await self._handle_delta(event.text)
                elif isinstance(event, TranscriptionStreamDone):
                    log.info("realtime transcription done")
                elif isinstance(event, RealtimeTranscriptionError):
                    log.error("realtime transcription error: %s", event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("realtime transcription stream failed: %s", exc)

    async def _handle_delta(self, text: str) -> None:
        if text in (".", "!", "?"):
            full_phrase = self.phrase + text
            wav_data = self._wav_bytes()
            self.audio = io.BytesIO()
            self.phrase = ""
            if not full_phrase.strip():
                return
            log.info("phrase (realtime pass): %s", full_phrase)

            batch_text = await self._transcribe_batch(wav_data)
            if batch_text:
                log.info("phrase (batch pass, custom vocabulary): %s", batch_text)

            # User hook: decide what to speak/display from both transcriptions
            spoken_text = processText(full_phrase, batch_text)
            if not spoken_text:
                return
            log.info("processText output: %s", spoken_text)
            await self.on_text(spoken_text, "transcription")

            # Text-to-speech: convert the processText() output to audio
            pcm = await self.synthesize(spoken_text)
            if pcm:
                await self.on_audio(pcm)
        else:
            self.phrase += str(text)

    def _wav_bytes(self) -> bytes:
        """Wrap the raw PCM buffer of the current phrase into a WAV container."""
        pcm = self.audio.getvalue()
        if not pcm:
            return b""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(pcm)
        return buf.getvalue()

    async def _transcribe_batch(self, wav_data: bytes) -> str:
        """Second pass: batch transcription biased with the custom vocabulary."""
        if not wav_data:
            return ""
        try:
            audio_file = File(content=wav_data, file_name="phrase.wav")

            def call() -> str:
                response = self.client.audio.transcriptions.complete(
                    model=BATCH_MODEL,
                    file=audio_file,
                    context_bias=CUSTOM_VOCABULARY,
                    language=LANGUAGE,
                )
                return response.text.strip()

            return await asyncio.to_thread(call)
        except Exception as exc:
            log.error("batch transcription failed: %s", exc)
            return ""
