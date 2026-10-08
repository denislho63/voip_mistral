"""Smoke tests: boot the real server over TLS and exercise the protocol.

The server is started as a subprocess WITHOUT mistralai and WITHOUT
MISTRAL_API_KEY (degraded mode) and WITHOUT PHONE_STREAM_TOKEN (random
token, read back from the server log). These tests verify:

- the static page is served (200) with the token, rejected (401) without
- the WebSocket handshake is accepted with the token, refused without
- text frames are echoed back on an authenticated connection
- binary (audio) blocks are dropped silently in degraded mode

Requires: websockets (requirements.txt), openssl for the certificate,
PHONE_STREAM_TOKEN set by the CI (falls back to a fixed local value).
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest
import websockets
from websockets.exceptions import InvalidStatus

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = os.environ.get("PHONE_STREAM_TOKEN", "ci-test-token")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    env = dict(os.environ)
    env["PHONE_STREAM_TOKEN"] = TOKEN
    env.pop("MISTRAL_API_KEY", None)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "server.py"), str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        else:
            raise RuntimeError("server did not start")
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture(scope="module")
def tls_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _get(url: str, tls_ctx, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, context=tls_ctx, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_static_page_requires_token(server, tls_ctx):
    status, _ = _get(f"https://127.0.0.1:{server}/", tls_ctx)
    assert status == 401


def test_static_page_bad_token(server, tls_ctx):
    status, _ = _get(f"https://127.0.0.1:{server}/?token=wrong", tls_ctx)
    assert status == 401


def test_static_page_with_token(server, tls_ctx):
    status, body = _get(f"https://127.0.0.1:{server}/?token={TOKEN}", tls_ctx)
    assert status == 200
    assert b"<!doctype html" in body.lower()


def test_static_page_bearer_header(server, tls_ctx):
    status, body = _get(
        f"https://127.0.0.1:{server}/",
        tls_ctx,
        {"Authorization": f"Bearer {TOKEN}"},
    )
    assert status == 200
    assert b"<!doctype html" in body.lower()


def test_path_traversal_blocked(server, tls_ctx):
    # the token must not be smuggled into the path: ?token= stays a query param
    status, body = _get(
        f"https://127.0.0.1:{server}/..%2Fserver.py?token={TOKEN}",
        tls_ctx,
    )
    assert status in (200, 403, 404)
    if status == 200:
        assert b"PIPELINES" not in body and b"import asyncio" not in body


async def test_websocket_requires_token(server, tls_ctx):
    with pytest.raises(InvalidStatus) as exc:
        conn = await websockets.connect(f"wss://127.0.0.1:{server}/phone", ssl=tls_ctx)
        await conn.close()
    assert exc.value.response.status_code == 401


async def test_websocket_echo_with_token(server, tls_ctx):
    async with websockets.connect(
        f"wss://127.0.0.1:{server}/phone?token={TOKEN}", ssl=tls_ctx
    ) as ws:
        await ws.send(json.dumps({"type": "text", "text": "hello ci"}))
        reply = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(reply)
        assert data == {"type": "text", "text": "hello ci"}


async def test_websocket_binary_dropped_in_degraded_mode(server, tls_ctx):
    async with websockets.connect(
        f"wss://127.0.0.1:{server}/phone?token={TOKEN}", ssl=tls_ctx
    ) as ws:
        await ws.send(b"\x01\x02\x03\x04")
        # No crash, connection stays open; a text frame still works after.
        await ws.send(json.dumps({"type": "text", "text": "still alive"}))
        data = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert data["text"] == "still alive"
