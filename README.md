# phone-stream

A phone-like web application served by a Python secure-WebSocket (wss) server.

- The **client** (mobile browser) captures microphone audio and streams it to
  the server; audio returned by the server is played on the headset.
- The server also sends **text** blocks, shown in the app, selectable and
  copyable to the clipboard with one tap. The user can send text back.
- The app is meant to run all the time. When the phone is locked (page
  hidden), the client stops sending data but keeps the text already received.

## The four functions (implemented)

In `server.py` these are now implemented and wired into the frame routing
(they were initially declared as required-but-unimplemented stubs):

| Function | Direction | Behavior |
|---|---|---|
| `processReceivedAudioBlock()` | client → server (binary mic audio) | feeds PCM into the realtime speech-to-text pipeline (`speech_pipeline.py`) |
| `sendAudioBlock()` | server → client (headset audio) | sends one binary block, tolerant to closed connections |
| `processReceivedTextBlock()` | client → server (text) | echoes text back to the client |
| `sendTextBlock()` | server → client (display/copy) | sends JSON text frame for display/clipboard |

### Speech-to-text pipeline (double transcription, custom vocabulary)

`speech_pipeline.py` bridges the phone's microphone to the Mistral APIs:

1. **Realtime pass**: PCM blocks stream into
   `client.audio.realtime.transcribe_stream`
   (`voxtral-mini-transcribe-realtime-2602`), producing text deltas.
2. **Batch pass with custom vocabulary**: when a phrase ends (`.`, `!`, `?`),
   the phrase audio is re-transcribed in batch via
   `client.audio.transcriptions.complete` (`voxtral-mini-latest`) with
   `context_bias=CUSTOM_VOCABULARY` for better accuracy on domain terms.
   The batch result (falling back to the realtime text on failure) is sent
   to the phone via `sendTextBlock()` and is visible/copyable in the app.

Enable it with:

```bash
pip install mistralai
export MISTRAL_API_KEY=...        # Windows: set MISTRAL_API_KEY=...
```

Without `mistralai` or `MISTRAL_API_KEY` the server still runs and serves
the app; audio blocks are dropped and a warning is logged.

The custom vocabulary lives in `speech_pipeline.py` (`CUSTOM_VOCABULARY`).
API keys must come from the environment — never hard-code them.

### processText() hook and text-to-speech

`processText(realtime_text, batch_text)` (in `process_text.py`) receives
**both transcriptions** of each finished phrase and returns the text to send
back. That text is:

1. sent to the phone as text via `sendTextBlock()` (displayed, copyable),
2. converted to speech via the `https://api.mistral.ai/v1/audio/speech`
   endpoint (`voxtral-mini-tts-2603`, `response_format="pcm"`) and sent as
   audio to the headset via `sendAudioBlock()` (resampled from 24 kHz to
   the headset's 16 kHz).

Default implementation: prefer the batch transcription, fall back to the
realtime one; return an empty string to say nothing. Customize it to plug in
an LLM, a translator, a command interpreter, etc.

## Protocol

| Frame | Payload |
|---|---|
| client → server, binary | raw audio block from the microphone |
| client → server, text | `{"type": "text", "text": "..."}` |
| server → client, binary | raw audio block for the headset |
| server → client, text | `{"type": "text", "text": "..."}` (optional `"tag"` shown as label) |

## Run

Linux / macOS:

```bash
bash run.sh            # generates self-signed certs on first run, serves on :8443
bash run.sh 9443       # custom port
```

Windows (cmd or double-click):

```bat
run.bat               :: generates self-signed certs on first run, serves on :8443
run.bat 9443          :: custom port
```

On Windows, `openssl` must be in `PATH` (Git for Windows bundles one:
`C:\Program Files\Git\usr\bin\openssl.exe`).

Requirements: Python 3.10+, `websockets` (`pip install -r requirements.txt`);
for speech-to-text also `mistralai` (`pip install mistralai`) plus the
`MISTRAL_API_KEY` environment variable.

Open `https://<server-ip>:8443/` on the phone. Accept the self-signed
certificate warning once. Mic capture and audio playback each require a user
tap on the app (browser autoplay/permission policies).

## Client behavior notes

- **Lock detection**: `document.visibilitychange` / `pagehide`. When the page
  becomes hidden the microphone recorder is stopped and nothing is sent;
  received text remains on screen. On unlock, streaming resumes if the mic
  was enabled.
- **Clipboard**: `navigator.clipboard` with a `textarea`+`execCommand` fallback.
- **Reconnect**: automatic every 2 s; the app keeps running indefinitely.
- **Audio playback**: received binary blocks are decoded as 16-bit PCM
  mono 16 kHz and played via WebAudio. Received audio is buffered until the
  user enables the speaker (autoplay policy), then played.

## Security

TLS 1.2+ with certificate in `certs/`. For production, replace the
self-signed certificate with one from a real CA (e.g. Let's Encrypt) and
serve behind your domain.
