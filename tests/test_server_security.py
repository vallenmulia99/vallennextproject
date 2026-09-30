"""Tests for server security, authentication, and origin controls (P0-2)."""

import asyncio
import json
import pytest
from unittest.mock import patch

from vallen_cli.core.server import handle_request, get_server_token, set_server_token


class MockStreamReader:
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    async def readline(self) -> bytes:
        if self._pos >= len(self._data):
            return b""
        newline_idx = self._data.find(b"\n", self._pos)
        if newline_idx == -1:
            res = self._data[self._pos:]
            self._pos = len(self._data)
            return res
        res = self._data[self._pos : newline_idx + 1]
        self._pos = newline_idx + 1
        return res

    async def readexactly(self, n: int) -> bytes:
        if self._pos + n > len(self._data):
            raise asyncio.IncompleteReadError(self._data[self._pos:], n)
        res = self._data[self._pos : self._pos + n]
        self._pos += n
        return res


class MockStreamWriter:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, b: bytes):
        self.data.extend(b)

    async def drain(self):
        pass

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_server_health_accessible_without_token():
    """GET /health should return 200 without token."""
    req = b"GET /health HTTP/1.1\r\nHost: 127.0.0.1:4096\r\n\r\n"
    reader = MockStreamReader(req)
    writer = MockStreamWriter()

    await handle_request(reader, writer)
    assert b"200 OK" in writer.data
    assert b'"status": "ok"' in writer.data


@pytest.mark.asyncio
async def test_server_models_requires_bearer_token():
    """GET /models without Bearer token must return 401."""
    req = b"GET /models HTTP/1.1\r\nHost: 127.0.0.1:4096\r\n\r\n"
    reader = MockStreamReader(req)
    writer = MockStreamWriter()

    await handle_request(reader, writer)
    assert b"401 Unauthorized" in writer.data


@pytest.mark.asyncio
async def test_server_models_with_valid_token():
    """GET /models with valid Bearer token returns 200."""
    set_server_token("test-secret-token")
    req = b"GET /models HTTP/1.1\r\nHost: 127.0.0.1:4096\r\nAuthorization: Bearer test-secret-token\r\n\r\n"
    reader = MockStreamReader(req)
    writer = MockStreamWriter()

    await handle_request(reader, writer)
    assert b"200 OK" in writer.data


@pytest.mark.asyncio
async def test_server_rejects_foreign_origin():
    """Request with untrusted Origin must return 403 Forbidden."""
    set_server_token("test-secret-token")
    req = b"GET /health HTTP/1.1\r\nHost: 127.0.0.1:4096\r\nOrigin: http://evil-site.com\r\n\r\n"
    reader = MockStreamReader(req)
    writer = MockStreamWriter()

    await handle_request(reader, writer)
    assert b"403 Forbidden" in writer.data


@pytest.mark.asyncio
async def test_server_chat_requires_application_json():
    """POST /chat with wrong content-type returns 415."""
    set_server_token("test-secret-token")
    body = b'{"prompt": "hello"}'
    req = (
        b"POST /chat HTTP/1.1\r\n"
        b"Host: 127.0.0.1:4096\r\n"
        b"Authorization: Bearer test-secret-token\r\n"
        b"Content-Type: text/plain\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    )
    reader = MockStreamReader(req)
    writer = MockStreamWriter()

    await handle_request(reader, writer)
    assert b"415 Unsupported Media Type" in writer.data
