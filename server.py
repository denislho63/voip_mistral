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

The four required functions are implemented and wired into the frame
routing:
    processReceivedAudioBlock()
    sendAudioBlock()
    processReceivedTextBlock()
    sendTextBlock()

Authentication: every request (static page and WebSocket handshake) must
present the access token, either as a `?token=` query parameter or as an
`Authorization: Bearer <token>` header. The token comes from the
PHONE_STREAM_TOKEN environment variable; if unset, a random token is
generated at startup and logged. The server only ever listens on TLS
(wss/https); plaintext access is impossible by design.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import mimetypes
import os
import re
import secrets
import ssl
import sys
import urllib.parse
import wave
from dataclasses import dataclass
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

from client_history import REGISTRY, ClientHistory, new_client_id
from process_command import process_command
from speech_pipeline import (
    SAMPLE_RATE,
    SpeechPipeline,
    pipeline_available,
)

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
CERT_FILE = ROOT / "certs" / "cert.pem"
KEY_FILE = ROOT / "certs" / "key.pem"

HOST = "0.0.0.0"
PORT = 8443
if len(sys.argv) > 1:
    try:
        PORT = int(sys.argv[1])
    except ValueError:
        pass  # non-numeric argument (e.g. pytest's): keep default

PING_INTERVAL = 20  # seconds; keeps NATs open, detects dead peers
MAX_MESSAGE_SIZE = 1 << 22  # 4 MiB, ample for audio blocks
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


@dataclass
class ClientSession:
    """Per-connection state: the client's socket and its speech pipeline.

    Created by phone_connection() and passed explicitly to the four
    audio/text hooks, instead of a module-level registry keyed by
    connection object. `client_id` is a stable identifier for this phone
    across the connection's lifetime; `history` keeps this client's
    texts/commands per vocabulary domain.
    """

    connection: ServerConnection
    client_id: str = ""
    pipeline: SpeechPipeline | None = None
    history: ClientHistory | None = None


ACCESS_TOKEN = os.environ.get("PHONE_STREAM_TOKEN") or secrets.token_urlsafe(24)


def _token_ok(request: Request) -> bool:
    """Validate the access token from the query string or Bearer header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        presented = auth[len("Bearer ") :].strip()
    else:
        presented = ""
    if not presented:
        parsed = urllib.parse.urlsplit(request.path)
        presented = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
    return secrets.compare_digest(presented, ACCESS_TOKEN)


def _client_id_ok(candidate: str) -> str:
    """Accept a client-provided persistent id, or generate a fresh one.

    The id lets the server recognize a phone across WebSocket
    reconnections and keep its per-domain history. It only needs to be
    unique and harmless; anything exotic is replaced.
    """
    candidate = (candidate or "").strip()
    if not candidate or len(candidate) > 64 or not CLIENT_ID_RE.fullmatch(candidate):
        return new_client_id()
    return candidate


CLIENT_ID_RE = re.compile(r"[A-Za-z0-9._-]+")


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


async def processReceivedAudioBlock(session: ClientSession, audio_block: bytes) -> None:
    """Handle one binary audio block received from a client microphone.

    Called automatically by the connection handler whenever a binary frame
    arrives. Feeds the PCM block into the realtime speech-to-text pipeline
    (mistralai) and, when the batch pass produced TTS audio, queues it for
    the headset.
    """
    pcm = _sanitize_pcm(audio_block)
    if not pcm:
        return

    pipeline = session.pipeline
    if pipeline is None:
        log.debug(
            "no pipeline for %s; dropping audio block",
            session.connection.remote_address,
        )
        return
    await pipeline.feed(pcm)


async def sendAudioBlock(session: ClientSession, audio_block: bytes) -> None:
    """Send one binary audio block to a client's headset.

    Designated outbound-audio hook. Serializes sends per connection and
    closes the connection if the client is gone.
    """
    try:
        await session.connection.send(audio_block)
    except ConnectionClosed:
        log.debug("sendAudioBlock: client %s gone", session.connection.remote_address)


async def processReceivedTextBlock(session: ClientSession, text: str) -> None:
    """Handle one text block received from a client.

    Called automatically by the connection handler for every text frame.
    Routes the user's text to the process_command() hook and sends the
    returned text back to the client (displayed, copyable) plus its
    text-to-speech rendering to the headset when the pipeline is enabled.
    """
    # Commands are attached to the pipeline's last classified domain so
    # that the process_command hook sees the same per-domain history as
    # the transcribed phrases.
    pipeline = session.pipeline
    domain = pipeline.last_domain if pipeline is not None else ""
    history = session.history.get(domain) if session.history is not None else None
    if session.history is not None:
        session.history.add_command(domain, text)
    response_text = process_command(
        text, client_id=session.client_id, domain=domain, history=history
    )
    if response_text:
        if session.history is not None:
            session.history.add_response(domain, response_text)
        await sendTextBlock(session, response_text)

    pipeline = session.pipeline
    if pipeline is not None and response_text:
        pcm = await pipeline.synthesize(response_text)
        if pcm:
            await sendAudioBlock(session, pcm)


async def sendTextBlock(session: ClientSession, text: str) -> None:
    """Send one text block to a client for display (selectable/copyable).

    Serializes sends per connection and closes the connection if the
    client is gone.
    """
    try:
        await session.connection.send(json.dumps({"type": "text", "text": text}))
    except ConnectionClosed:
        log.debug("sendTextBlock: client %s gone", session.connection.remote_address)


# --------------------------------------------------------------------------
# Pipeline lifecycle — bound to the connection handler
# --------------------------------------------------------------------------


async def start_pipeline(session: ClientSession) -> None:
    """Create the speech pipeline for a new client, if the environment allows."""
    connection = session.connection
    if not pipeline_available():
        if connection.remote_address:
            log.info(
                "speech pipeline disabled (set MISTRAL_API_KEY and pip install "
                "mistralai to enable); serving app without transcription"
            )
        return

    async def on_text(text: str, tag: str) -> None:
        await sendTextBlock(session, text)

    async def on_audio(pcm: bytes) -> None:
        await sendAudioBlock(session, pcm)

    try:
        session.pipeline = SpeechPipeline(
            on_text, on_audio, client_id=session.client_id, history=session.history
        )
        log.info("speech pipeline started for %s", connection.remote_address)
    except Exception as exc:
        log.error("failed to start speech pipeline: %s", exc)


async def stop_pipeline(session: ClientSession) -> None:
    """Stop and discard the pipeline of a disconnecting client."""
    pipeline = session.pipeline
    session.pipeline = None
    if pipeline is not None:
        await pipeline.stop()
        log.info("speech pipeline stopped for %s", session.connection.remote_address)


# --------------------------------------------------------------------------
# Frame routing
# --------------------------------------------------------------------------


async def handle_text_frame(session: ClientSession, raw: str) -> None:
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
        log.warning(
            "ignoring malformed text frame from %s",
            session.connection.remote_address,
        )
        return

    if len(text) > MAX_TEXT_LEN:
        log.warning(
            "oversized text frame from %s, rejecting", session.connection.remote_address
        )
        await session.connection.close(1009, "text message too long")
        return

    try:
        await processReceivedTextBlock(session, text)
    except NotImplementedError:
        log.info(
            "processReceivedTextBlock() not implemented; got %d chars from %s",
            len(text),
            session.connection.remote_address,
        )


async def handle_binary_frame(session: ClientSession, data: bytes) -> None:
    """Dispatch a binary (audio) frame to the hook."""
    try:
        await processReceivedAudioBlock(session, data)
    except NotImplementedError:
        log.debug(
            "processReceivedAudioBlock() not implemented; dropped %d bytes from %s",
            len(data),
            session.connection.remote_address,
        )


def _handshake_client_id(connection: ServerConnection) -> str:
    """Read the client_id passed in the WebSocket handshake query string."""
    path = getattr(connection, "request", None)
    path = getattr(path, "path", "") or ""
    parsed = urllib.parse.urlsplit(path)
    return urllib.parse.parse_qs(parsed.query).get("client_id", [""])[0]


# --------------------------------------------------------------------------
# WebSocket connection handler
# --------------------------------------------------------------------------


async def phone_connection(connection: ServerConnection) -> None:
    """Lifecycle for one phone client."""
    remote = connection.remote_address
    log.info("client connected: %s", remote)

    client_id = _client_id_ok(_handshake_client_id(connection))
    session = ClientSession(
        connection=connection, client_id=client_id, history=REGISTRY.register(client_id)
    )
    log.info("client id: %s", client_id)
    await start_pipeline(session)
    try:
        async for message in connection:
            if isinstance(message, str):
                await handle_text_frame(session, message)
            else:
                await handle_binary_frame(session, message)
    except ConnectionClosed:
        pass
    finally:
        await stop_pipeline(session)
        # History is intentionally kept: the client reconnects with the
        # same id and resumes it. A TTL sweeps inactive clients; a server
        # restart clears everything (in-memory only).
        log.info("client disconnected: %s (id %s)", remote, session.client_id)


# --------------------------------------------------------------------------
# Static file serving (same TLS port, via process_request)
# --------------------------------------------------------------------------


def http_response(status: int, reason: str, body: bytes, content_type: str) -> Response:
    return Response(
        status,
        reason,
        Headers(
            [
                ("Content-Type", content_type),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
            ]
        ),
        body,
    )


async def serve_static(request: Request) -> Response:
    """Serve static/index.html (and other static files) for plain HTTPS GETs.

    File reads run in a worker thread so large files never block the
    event loop.
    """
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
    body = await asyncio.to_thread(file.read_bytes)
    return http_response(200, "OK", body, mime)


async def process_request(
    connection: ServerConnection, request: Request
) -> Response | None:
    """Authenticate the request, then route non-WebSocket requests to the
    static server.

    Returning None lets the WebSocket handshake proceed; returning a
    Response serves it as a plain HTTPS request. Every request - static
    page or WebSocket handshake - must carry the access token (query
    parameter `token` or `Authorization: Bearer` header). The server
    only listens on TLS, so plaintext access is impossible by design.
    """
    is_websocket = request.headers.get("Upgrade", "").lower() == "websocket"
    if not _token_ok(request):
        log.warning(
            "unauthorized %s request for %s from %s",
            "websocket" if is_websocket else "https",
            request.path.split("?", 1)[0],
            connection.remote_address,
        )
        return http_response(401, "Unauthorized", b"unauthorized", "text/plain")
    if is_websocket:
        return None  # WebSocket upgrade: handled by phone_connection()
    return await serve_static(request)


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
        scheme_host = f"https://<your-ip>:{PORT}"
        if os.environ.get("PHONE_STREAM_TOKEN"):
            log.info(
                "phone-stream server listening on %s:%d (token from PHONE_STREAM_TOKEN)",
                HOST,
                PORT,
            )
        else:
            log.info(
                "phone-stream server listening on %s:%d "
                "(random access token for this run)",
                HOST,
                PORT,
            )
        log.info("app:   %s/?token=%s", scheme_host, ACCESS_TOKEN)
        log.info(
            "ws:    wss://<your-ip>:%d/phone (Authorization: Bearer or ?token=)", PORT
        )
        await asyncio.get_running_loop().create_future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("shut down cleanly")
