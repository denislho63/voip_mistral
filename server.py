#!/usr/bin/env python3
"""
phone-stream server
===================

A secure WebSocket (wss) server that also serves the phone web application
(static/index.html) over HTTPS on the same TLS port.

Protocol
--------
Client -> Server (binary) : raw audio blocks captured from the microphone
Client -> Server (text)   : JSON  {"type": "text", "text": "..."}
Server -> Client (binary) : raw audio blocks, played on the headset
Server -> Client (text)   : JSON  {"type": "text", "text": "..."} shown to
                            the user (selectable, copyable to clipboard)

Four functions are declared but NOT implemented yet, as required:
    processReceivedAudioBlock()
    sendAudioBlock()
    processReceivedTextBlock()
    sendTextBlock()

They are async stubs raising NotImplementedError. The surrounding plumbing
(TLS, static serving, connection handling, frame routing) is complete and
calls these stubs, so implementing them later plugs the real media/text
logic into an already working server.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import mimetypes
import ssl
import sys
import wave
from pathlib import Path

# Windows: the default Proactor event loop raises spurious errors like
# "Exception in callback _ProactorBasePipeTransport._call_connection_lost"
# when SSL sockets are closed during shutdown. The Selector loop does not
# and is fully sufficient for this server (no subprocess support needed).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from speech_pipeline import SAMPLE_RATE, SpeechPipeline, pipeline_available

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
CERT_FILE = ROOT / "certs" / "cert.pem"
KEY_FILE = ROOT / "certs" / "key.pem"

HOST = "0.0.0.0"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8443

PING_INTERVAL = 20            # seconds; keeps NATs open, detects dead peers
MAX_MESSAGE_SIZE = 1 << 22    # 4 MiB, ample for audio blocks
MAX_TEXT_LEN = 64 * 1024

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("phone-stream")

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


# --------------------------------------------------------------------------
# Audio/text pipeline state (per connection)
# --------------------------------------------------------------------------

PIPELINES: dict[ServerConnection, "SpeechPipeline"] = {}


def _wav_bytes(pcm: bytes) -> bytes:
    """Wrap raw PCM (16-bit mono 16 kHz) into a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm)
    return buf.getvalue()


def _sanitize_pcm(block: bytes) -> bytes:
    """Keep only complete 16-bit samples (drop a trailing odd byte)."""
    return block[: len(block) - (len(block) % 2)]


# --------------------------------------------------------------------------
# The four required functions — now implemented
# --------------------------------------------------------------------------

async def processReceivedAudioBlock(
    connection: ServerConnection, audio_block: bytes
) -> None:
    """Handle one binary audio block received from a client microphone.

    Called automatically by the connection handler whenever a binary frame
    arrives. Feeds the PCM block into the realtime speech-to-text pipeline
    (mistralai) and, when the batch pass produced TTS audio, queues it for
    the headset.
    """
    pcm = _sanitize_pcm(audio_block)
    if not pcm:
        return

    pipeline = PIPELINES.get(connection)
    if pipeline is None:
        log.debug("no pipeline for %s; dropping audio block", connection.remote_address)
        return
    await pipeline.feed(pcm)


async def sendAudioBlock(connection: ServerConnection, audio_block: bytes) -> None:
    """Send one binary audio block to a client's headset.

    Designated outbound-audio hook. Serializes sends per connection and
    closes the connection if the client is gone.
    """
    try:
        await connection.send(audio_block)
    except ConnectionClosed:
        log.debug("sendAudioBlock: client %s gone", connection.remote_address)


async def processReceivedTextBlock(
    connection: ServerConnection, text: str
) -> None:
    """Handle one text block received from a client.

    Called automatically by the connection handler for every text frame.
    Echoes the text back to the client (visible in the app, copyable),
    prefixed to distinguish it from server-generated text.
    """
    await sendTextBlock(connection, f"(from you) {text}")


async def sendTextBlock(connection: ServerConnection, text: str) -> None:
    """Send one text block to a client for display (selectable/copyable).

    Serializes sends per connection and closes the connection if the
    client is gone.
    """
    try:
        await connection.send(json.dumps({"type": "text", "text": text}))
    except ConnectionClosed:
        log.debug("sendTextBlock: client %s gone", connection.remote_address)


# --------------------------------------------------------------------------
# Pipeline lifecycle — bound to the connection handler
# --------------------------------------------------------------------------

async def start_pipeline(connection: ServerConnection) -> None:
    """Create the speech pipeline for a new client, if the environment allows."""
    if not pipeline_available():
        if connection.remote_address:
            log.info(
                "speech pipeline disabled (set MISTRAL_API_KEY and pip install "
                "mistralai to enable); serving app without transcription"
            )
        return

    async def on_text(text: str, tag: str) -> None:
        await sendTextBlock(connection, text)

    async def on_audio(pcm: bytes) -> None:
        await sendAudioBlock(connection, pcm)

    try:
        PIPELINES[connection] = SpeechPipeline(on_text, on_audio)
        log.info("speech pipeline started for %s", connection.remote_address)
    except Exception as exc:
        log.error("failed to start speech pipeline: %s", exc)


async def stop_pipeline(connection: ServerConnection) -> None:
    """Stop and discard the pipeline of a disconnecting client."""
    pipeline = PIPELINES.pop(connection, None)
    if pipeline is not None:
        await pipeline.stop()
        log.info("speech pipeline stopped for %s", connection.remote_address)


# --------------------------------------------------------------------------
# Frame routing
# --------------------------------------------------------------------------

async def handle_text_frame(connection: ServerConnection, raw: str) -> None:
    """Decode/validate a text frame, then dispatch to the hook."""
    text: str | None
    try:
        message = json.loads(raw)
        if isinstance(message, dict) and isinstance(message.get("text"), str):
            text = message["text"]
        else:
            text = None
    except (json.JSONDecodeError, ValueError):
        text = raw  # plain-text frame, not JSON-wrapped

    if text is None:
        log.warning("ignoring malformed text frame from %s", connection.remote_address)
        return

    if len(text) > MAX_TEXT_LEN:
        log.warning("oversized text frame from %s, rejecting", connection.remote_address)
        await connection.close(1009, "text message too long")
        return

    try:
        await processReceivedTextBlock(connection, text)
    except NotImplementedError:
        log.info(
            "processReceivedTextBlock() not implemented; got %d chars from %s",
            len(text),
            connection.remote_address,
        )


async def handle_binary_frame(connection: ServerConnection, data: bytes) -> None:
    """Dispatch a binary (audio) frame to the hook."""
    try:
        await processReceivedAudioBlock(connection, data)
    except NotImplementedError:
        log.debug(
            "processReceivedAudioBlock() not implemented; dropped %d bytes from %s",
            len(data),
            connection.remote_address,
        )


# --------------------------------------------------------------------------
# WebSocket connection handler
# --------------------------------------------------------------------------

async def phone_connection(connection: ServerConnection) -> None:
    """Lifecycle for one phone client."""
    remote = connection.remote_address
    log.info("client connected: %s", remote)
    await start_pipeline(connection)
    try:
        async for message in connection:
            if isinstance(message, str):
                await handle_text_frame(connection, message)
            else:
                await handle_binary_frame(connection, message)
    except ConnectionClosed:
        pass
    finally:
        await stop_pipeline(connection)
        log.info("client disconnected: %s", remote)


# --------------------------------------------------------------------------
# Static file serving (same TLS port, via process_request)
# --------------------------------------------------------------------------

def http_response(status: int, reason: str, body: bytes, content_type: str) -> Response:
    return Response(
        status,
        reason,
        Headers([
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
        ]),
        body,
    )


def serve_static(request: Request) -> Response:
    """Serve static/index.html (and other static files) for plain HTTPS GETs."""
    resource = request.path.split("?", 1)[0].split("#", 1)[0]

    if resource in ("/", "/index.html", "/index.htm"):
        file = STATIC_DIR / "index.html"
    else:
        candidate = (STATIC_DIR / resource.lstrip("/")).resolve()
        if not candidate.is_relative_to(STATIC_DIR.resolve()):
            return http_response(403, "Forbidden", b"forbidden", "text/plain")
        file = candidate

    if not file.is_file():
        return http_response(404, "Not Found", b"not found", "text/plain")

    mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    return http_response(200, "OK", file.read_bytes(), mime)


def process_request(
    connection: ServerConnection, request: Request
) -> Response | None:
    """Route non-WebSocket requests to the static server.

    Returning None lets the WebSocket handshake proceed; returning a
    Response serves it as a plain HTTPS request.
    """
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None  # WebSocket upgrade: handled by phone_connection()
    return serve_static(request)


# --------------------------------------------------------------------------
# TLS + startup
# --------------------------------------------------------------------------

def build_ssl_context() -> ssl.SSLContext:
    if not CERT_FILE.is_file() or not KEY_FILE.is_file():
        sys.stderr.write(
            f"""TLS certificates missing: {CERT_FILE} / {KEY_FILE}
Run:  ./run.sh   (or)  bash gen_certs.sh
to generate a self-signed certificate first.
"""
        )
        sys.exit(1)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=str(CERT_FILE), keyfile=str(KEY_FILE))
    return ctx


async def main() -> None:
    ctx = build_ssl_context()
    async with serve(
        phone_connection,
        host=HOST,
        port=PORT,
        ssl=ctx,
        process_request=process_request,
        max_size=MAX_MESSAGE_SIZE,
        ping_interval=PING_INTERVAL,
        ping_timeout=PING_INTERVAL,
        max_queue=None,
    ):
        log.info(
            "phone-stream server listening on %s:%d "
            "(app: https://<your-ip>:%d/  ws: wss://<your-ip>:%d/)",
            HOST,
            PORT,
            PORT,
            PORT,
        )
        await asyncio.get_running_loop().create_future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("shut down cleanly")
