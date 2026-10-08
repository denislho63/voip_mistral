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

import array
import asyncio
import io
import logging
import os
import sys
import wave
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from detection_classification import find_domain, vocabulary_for_domain
from process_text import processText

ROOT = Path(__file__).resolve().parent

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
# Voice used for text-to-speech. Override with MISTRAL_TTS_VOICE.
# Run `python list_voices.py` to see the voice ids available on your account.
TTS_VOICE = os.environ.get("MISTRAL_TTS_VOICE", "5a271406-039d-46fe-835b-fbbb00eaf08d")
SAMPLE_RATE = 16000
LANGUAGE = "fr"

# Custom vocabulary applied to the batch (second) transcription pass.
# By default it is loaded from custom_vocabulary.txt (one term per line,
# '#' starts a comment); set PHONE_STREAM_VACABULARY to point to another
# file, or PHONE_STREAM_VOCABULARY to an inline comma-separated list.
VOCABULARY_FILE = ROOT / "custom_vocabulary.txt"


def _load_custom_vocabulary() -> list[str]:
    inline = os.environ.get("PHONE_STREAM_VOCABULARY", "").strip()
    if inline:
        return [t.strip() for t in inline.split(",") if t.strip()]
    path = Path(os.environ.get("PHONE_STREAM_VACABULARY", VOCABULARY_FILE))
    if not path.is_file():
        return []
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        term = line.split("#", 1)[0].strip()
        if term:
            terms.append(term)
    return terms


CUSTOM_VOCABULARY = _load_custom_vocabulary()

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
    """Linearly resample 16-bit mono PCM between rates (stdlib only).

    Bulk-unpacks the samples with array and repacks the result in one
    shot, which is dramatically faster than a per-sample to_bytes() loop
    for the phrase-length buffers produced by the TTS pass.
    """
    if not pcm or src_rate == dst_rate:
        return pcm
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    n_src = len(samples)
    if n_src == 0:
        return b""
    n_dst = int(n_src * dst_rate / src_rate)
    if n_dst == 0:
        out = array.array("h", [samples[0]])
    elif n_dst == 1:
        out = array.array("h", [samples[-1]])
    else:
        out = array.array("h", bytes(2 * n_dst))
        step = (n_src - 1) / (n_dst - 1)
        for i in range(n_dst):
            pos = i * step
            i0 = int(pos)
            i1 = min(i0 + 1, n_src - 1)
            frac = pos - i0
            out[i] = int(samples[i0] * (1.0 - frac) + samples[i1] * frac)
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


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
    floats = array.array("f")
    floats.frombytes(raw[: n * 4])
    if sys.byteorder == "big":
        floats.byteswap()
    n_dst = int(n * dst_rate / src_rate)
    if n_dst == 0:
        return array.array(
            "h", [int(max(-1.0, min(1.0, floats[-1])) * 32767)]
        ).tobytes()
    out = array.array("h", bytes(2 * n_dst))
    if n_dst == 1:
        out[0] = int(max(-1.0, min(1.0, floats[0])) * 32767)
    else:
        step = (n - 1) / (n_dst - 1)
        for i in range(n_dst):
            pos = i * step
            i0 = int(pos)
            i1 = min(i0 + 1, n - 1)
            frac = pos - i0
            value = floats[i0] * (1.0 - frac) + floats[i1] * frac
            out[i] = int(max(-1.0, min(1.0, value)) * 32767)
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


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
            # Domain classification from the realtime text: pick the
            # most fitting vocabulary before the batch (second) pass.
            domain = await self._classify(full_phrase)
            vocabulary = vocabulary_for_domain(domain)
            batch_text = await self._transcribe_batch(wav_data, vocabulary)
            if batch_text:
                log.info("phrase (batch pass, domain=%s): %s", domain, batch_text)

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

    async def _classify(self, phrase: str) -> str:
        """Classify the realtime text into a domain (non-blocking)."""
        return await asyncio.to_thread(find_domain, phrase, self.client)

    async def _transcribe_batch(self, wav_data: bytes, vocabulary: list[str]) -> str:
        """Second pass: batch transcription biased with a domain vocabulary.

        An empty vocabulary disables context_bias for this phrase.
        """
        if not wav_data:
            return ""
        try:
            audio_file = File(content=wav_data, file_name="phrase.wav")

            def call() -> str:
                kwargs = {}
                if vocabulary:
                    kwargs["context_bias"] = vocabulary
                response = self.client.audio.transcriptions.complete(
                    model=BATCH_MODEL,
                    file=audio_file,
                    language=LANGUAGE,
                    **kwargs,
                )
                return response.text.strip()

            return await asyncio.to_thread(call)
        except Exception as exc:
            log.error("batch transcription failed: %s", exc)
            return ""
