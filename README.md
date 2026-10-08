# phone-stream

[![CI](https://github.com/denislho63/voip_mistral/actions/workflows/ci.yml/badge.svg)](https://github.com/denislho63/voip_mistral/actions/workflows/ci.yml)

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

### Domain-adaptive vocabulary (classification)

Before the batch pass, the **realtime text of the finished phrase is
classified into a domain** (`detection_classification.py`, small chat
model, temperature 0). The batch transcription then uses the vocabulary
of that domain as `context_bias`:

- Domain vocabularies live in `vocabularies/<domaine>.txt` (one term
  per line, `#` starts a comment). Example: `vocabularies/pastoral.txt`,
  `vocabularies/theologique.txt`, `vocabularies/informatique.txt`.
- Unknown domain or missing file disables `context_bias` for that
  phrase (empty vocabulary).
- Override the classification model with
  `MISTRAL_CLASSIFICATION_MODEL` (default `mistral-small-latest`).
- Without an API key or if classification fails, the vocabulary is
  empty — transcription never breaks because of classification.

Optional global override (all domains): `PHONE_STREAM_VOCABULARY=term1,term2`
(inline list) or `PHONE_STREAM_VACABULARY=/path/to/file` (one term per
line, `#` starts a comment).
API keys must come from the environment — never hard-code them.

### Client identity and per-domain history

Each connected phone gets a `client_id` (logged at connect, unique per
connection). Every finished phrase and every user-typed command/response
is recorded in that client's history, **split by vocabulary domain**:
a phrase classified "pastoral" goes to the pastoral history of that
client, etc.

Both hooks receive this context:

```python
def processText(realtime_text, batch_text, client_id="", domain="", history=None): ...
def process_command(text, client_id="", domain="", history=None): ...
```

`history` is the list of this client's records **for the detected
domain** (oldest first), each `{"role": "phrase"|"response"|"command",
"text": ..., "domain": ...}`. Commands are attached to the last domain
classified from the audio. Use it to build answers aware of the
conversation (e.g. pass it to an LLM as context).

- The phone app stores its `client_id` in localStorage and sends it on
  every WebSocket connect: **the history survives reconnections** (the
  server logs "history resumed"). Without a provided id, a fresh one is
  generated per connection.
- Histories are **in-memory only**: a server restart forgets everything
  (as intended). An idle client's history is swept after
  `PHONE_STREAM_HISTORY_TTL` seconds (default 3600); each activity
  extends it. `PHONE_STREAM_HISTORY` caps entries per domain (default 50).
- With several phones connected at once, each `client_id` has its own
  isolated history — responses never mix between clients.

### processText() and process_command() hooks

`processText(realtime_text, batch_text, client_id, domain, history)`
(in `process_text.py`) receives **both transcriptions** of each finished
phrase plus the client/domain context and returns the text to send
back. That text is:

1. sent to the phone as text via `sendTextBlock()` (displayed, copyable),
2. converted to speech via the `https://api.mistral.ai/v1/audio/speech`
   endpoint (`voxtral-mini-tts-2603`, `response_format="pcm"`) and sent as
   audio to the headset via `sendAudioBlock()` (resampled from 24 kHz to
   the headset's 16 kHz).

Default implementation: prefer the batch transcription, fall back to the
realtime one; return an empty string to say nothing. Customize it to plug in
an LLM, a translator, a command interpreter, etc.

`process_command(text)` (in `process_command.py`) receives the **text typed
by the user** in the app and returns the response text, which is likewise
sent as text and converted to speech. Default: echoes the received text
(the server speaks it back).

## Protocol

| Frame | Payload |
|---|---|
| client → server, binary | raw audio block from the microphone |
| client → server, text | `{"type": "text", "text": "..."}` |
| server → client, binary | raw audio block for the headset |
| server → client, text | `{"type": "text", "text": "..."}` (optional `"tag"` shown as label) |

## Development

- **Lint / format**: `ruff check .` and `ruff format --check .` (config in
  `pyproject.toml`; run `pip install ruff`).
- **Tests**: `pip install -r requirements.txt pytest pytest-asyncio`, then
  `pytest tests/` (generate certs with `bash gen_certs.sh` first; set
  `PHONE_STREAM_TOKEN=whatever` to pin the token).
- **CI**: GitHub Actions (`.github/workflows/ci.yml`) — lint + tests on
  Python 3.10 and 3.12, server booted in degraded mode (no API key).

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

- **TLS only**: the server has no plaintext port; both the app and the
  WebSocket must be loaded over https/wss (TLS 1.2+), certificate in
  `certs/`. For production, replace the self-signed certificate with one
  from a real CA (e.g. Let's Encrypt) and serve behind your domain.
- **Access token**: every request (static page and WebSocket handshake)
  must present the access token, either as a `?token=` query parameter or
  an `Authorization: Bearer <token>` header. Without it the server answers
  401. Set the token via:
  ```bash
  export PHONE_STREAM_TOKEN=...   # Windows: set PHONE_STREAM_TOKEN=...
  ```
  If unset, the server generates a random token at startup and logs the
  ready-to-open app URL (`https://<ip>:<port>/?token=...`). The phone
  client reads the token from the page URL and forwards it to the
  WebSocket automatically.
