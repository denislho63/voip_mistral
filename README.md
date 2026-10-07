# phone-stream

A phone-like web application served by a Python secure-WebSocket (wss) server.

- The **client** (mobile browser) captures microphone audio and streams it to
  the server; audio returned by the server is played on the headset.
- The server also sends **text** blocks, shown in the app, selectable and
  copyable to the clipboard with one tap. The user can send text back.
- The app is meant to run all the time. When the phone is locked (page
  hidden), the client stops sending data but keeps the text already received.

## The four functions (defined, not implemented)

In `server.py` these are declared as required but are stubs raising
`NotImplementedError`. All plumbing (TLS, static serving, connection
handling, frame routing) is complete and calls into them:

| Function | Direction | Called by |
|---|---|---|
| `processReceivedAudioBlock()` | client → server (binary mic audio) | the framework, for every binary frame |
| `sendAudioBlock()` | server → client (headset audio) | your media logic |
| `processReceivedTextBlock()` | client → server (text) | the framework, for every text frame |
| `sendTextBlock()` | server → client (display/copy) | your logic |

Implement them to plug in real media/text processing; the surrounding server
is already working.

## Protocol

| Frame | Payload |
|---|---|
| client → server, binary | raw audio block from the microphone |
| client → server, text | `{"type": "text", "text": "..."}` |
| server → client, binary | raw audio block for the headset |
| server → client, text | `{"type": "text", "text": "..."}` (optional `"tag"` shown as label) |

## Run

```bash
bash run.sh            # generates self-signed certs on first run, serves on :8443
bash run.sh 9443       # custom port
```

Requirements: Python 3.10+, `websockets` (`pip install -r requirements.txt`).

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
