"""VALLEN CLI — Headless REST & SSE Server.

Mirrors OpenCode server/index.ts:
Runs an async HTTP daemon on localhost supporting:
- GET  /health   -> Healthcheck
- GET  /models   -> List available models
- GET  /sessions -> List sessions
- POST /chat     -> SSE streaming chat completions with tool execution
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import secrets
import sys
import urllib.parse
from pathlib import Path
from typing import Any

from .config import get_config
from .workspace import get_workspace
from .session import get_session_manager
from ..providers.registry import get_registry
from .agent import run_agent, AgentEvent
from .. import __version__

logger = logging.getLogger(__name__)

# Server auth token state
_SERVER_TOKEN: str | None = None
_ALLOWED_HOSTS: set[str] = {"127.0.0.1", "localhost", "::1"}
_MAX_CONTENT_LENGTH: int = 1_048_576  # 1 MB


def get_server_token() -> str:
    global _SERVER_TOKEN
    if not _SERVER_TOKEN:
        cfg = get_config()
        configured_token = cfg.get("server", "token", default="") if hasattr(cfg, "get") else ""
        _SERVER_TOKEN = configured_token or secrets.token_urlsafe(24)
    return _SERVER_TOKEN


def set_server_token(token: str | None) -> None:
    global _SERVER_TOKEN
    _SERVER_TOKEN = token


def _send_json(writer: asyncio.StreamWriter, status_code: int, json_str: str, origin: str | None = None) -> None:
    status_text = {
        200: "OK",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        413: "Payload Too Large",
        415: "Unsupported Media Type",
        500: "Internal Server Error",
    }.get(status_code, "OK")
    body = json_str.encode("utf-8")
    headers = [
        f"HTTP/1.1 {status_code} {status_text}",
        "Content-Type: application/json",
        f"Content-Length: {len(body)}",
        "Connection: close",
    ]
    if origin:
        headers.append(f"Access-Control-Allow-Origin: {origin}")
    headers.extend(["", ""])
    writer.write("\r\n".join(headers).encode("utf-8") + body)


async def handle_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10.0)
        except asyncio.TimeoutError:
            writer.close()
            return

        if not line:
            writer.close()
            return

        request_line = line.decode(errors="replace").strip()
        parts = request_line.split()
        if len(parts) < 2:
            writer.close()
            return

        method, full_path = parts[0].upper(), parts[1]
        url = urllib.parse.urlparse(full_path)
        path = url.path

        headers: dict[str, str] = {}
        while True:
            try:
                hline = await asyncio.wait_for(reader.readline(), timeout=10.0)
            except asyncio.TimeoutError:
                writer.close()
                return
            if not hline or hline in (b"\r\n", b"\n"):
                break
            header_str = hline.decode(errors="replace").strip()
            if ":" in header_str:
                k, _, v = header_str.partition(":")
                headers[k.strip().lower()] = v.strip()

        # ── 1. Host header validation (prevent DNS rebinding) ──
        host_header = headers.get("host", "")
        host_val = host_header.split(":")[0].strip().lower()
        if host_val and host_val not in _ALLOWED_HOSTS:
            _send_json(writer, 403, json.dumps({"error": f"Invalid Host: {host_header}"}))
            return

        # ── 2. Origin check (CORS allowlist, no wildcard *) ──
        origin = headers.get("origin")
        if origin:
            # Only allow if origin host is loopback/allowed
            parsed_origin = urllib.parse.urlparse(origin)
            origin_host = parsed_origin.hostname or ""
            if origin_host.lower() not in _ALLOWED_HOSTS:
                _send_json(writer, 403, json.dumps({"error": f"Forbidden Origin: {origin}"}))
                return

        # ── 3. Health check (token optional) ──
        if method == "GET" and path in ("/health", "/"):
            response_data = json.dumps({"status": "ok", "app": "vallen-cli", "version": __version__})
            _send_json(writer, 200, response_data, origin=origin)
            return

        # ── 4. Token Authentication (Bearer token) ──
        expected_token = get_server_token()
        auth_header = headers.get("authorization", "")
        token = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

        if not token or not hmac.compare_digest(token, expected_token):
            _send_json(writer, 401, json.dumps({"error": "Unauthorized: valid Bearer token required"}), origin=origin)
            return

        # ── 5. Content-Length check & Read body ──
        body_bytes = b""
        if "content-length" in headers:
            try:
                length = int(headers["content-length"])
            except ValueError:
                _send_json(writer, 400, json.dumps({"error": "Invalid Content-Length"}), origin=origin)
                return

            if length < 0:
                _send_json(writer, 400, json.dumps({"error": "Negative Content-Length"}), origin=origin)
                return
            if length > _MAX_CONTENT_LENGTH:
                _send_json(writer, 413, json.dumps({"error": f"Payload too large. Max: {_MAX_CONTENT_LENGTH} bytes"}), origin=origin)
                return

            try:
                body_bytes = await asyncio.wait_for(reader.readexactly(length), timeout=30.0)
            except asyncio.TimeoutError:
                _send_json(writer, 408, json.dumps({"error": "Request body read timed out"}), origin=origin)
                return

        # Route requests
        if method == "GET" and path == "/models":
            registry = get_registry()
            provider = registry.active()
            models = []
            if provider:
                try:
                    m_list = await provider.list_models()
                    models = [{"id": m.id, "display_name": m.display_name, "provider": m.provider} for m in m_list]
                except Exception:
                    models = [{"id": provider.model, "display_name": provider.model, "provider": provider.name}]
            _send_json(writer, 200, json.dumps({"models": models}), origin=origin)
            return

        if method == "GET" and path == "/sessions":
            sess_mgr = get_session_manager()
            sessions = sess_mgr.list_all_for_project()
            _send_json(writer, 200, json.dumps({"sessions": sessions}), origin=origin)
            return

        if method == "POST" and path == "/chat":
            content_type = headers.get("content-type", "")
            if not content_type.lower().startswith("application/json"):
                _send_json(writer, 415, json.dumps({"error": "Content-Type must be application/json"}), origin=origin)
                return
            await _handle_chat_sse(writer, body_bytes, origin=origin)
            return

        # 404 fallback
        _send_json(writer, 404, json.dumps({"error": "Not found"}), origin=origin)
    except Exception as e:
        try:
            _send_json(writer, 500, json.dumps({"error": str(e)}))
        except Exception:
            pass
    finally:
        try:
            await writer.drain()
            writer.close()
        except Exception:
            pass


async def _handle_chat_sse(writer: asyncio.StreamWriter, body_bytes: bytes, origin: str | None = None) -> None:
    try:
        payload = json.loads(body_bytes.decode(errors="replace"))
    except Exception:
        _send_json(writer, 400, json.dumps({"error": "Invalid JSON body"}), origin=origin)
        return

    prompt = payload.get("prompt", "")
    if not prompt:
        _send_json(writer, 400, json.dumps({"error": "prompt is required"}), origin=origin)
        return

    project = payload.get("project", "")
    if project:
        p_path = Path(project).expanduser().resolve()
        if not p_path.exists() or not p_path.is_dir():
            _send_json(writer, 400, json.dumps({"error": f"Invalid project directory: {project}"}), origin=origin)
            return
        ws = get_workspace()
        ws.set_active_project(str(p_path))

    session_id = payload.get("session_id", "")
    sess_mgr = get_session_manager()
    if session_id:
        sess_mgr.resume(session_id)
    elif not sess_mgr.session_id:
        sess_mgr.start_new()

    # Send SSE Headers
    headers = [
        "HTTP/1.1 200 OK",
        "Content-Type: text/event-stream",
        "Cache-Control: no-cache",
        "Connection: keep-alive",
    ]
    if origin:
        headers.append(f"Access-Control-Allow-Origin: {origin}")
    headers.extend(["", ""])
    writer.write("\r\n".join(headers).encode("utf-8"))
    await writer.drain()

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    cancel_event = asyncio.Event()

    def on_event(ev: AgentEvent) -> None:
        if ev.kind == "stream_reset":
            queue.put_nowait({"kind": "stream_reset", "data": {}})
            return
        queue.put_nowait({"kind": ev.kind, "data": ev.data})

    async def run_task():
        try:
            res = await run_agent(prompt, on_event=on_event, cancel_event=cancel_event)
            queue.put_nowait({"kind": "done", "data": res})
        except asyncio.CancelledError:
            pass
        except Exception as err:
            queue.put_nowait({"kind": "error", "data": str(err)})
        finally:
            queue.put_nowait(None)

    agent_task = asyncio.create_task(run_task())

    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            sse_data = f"data: {json.dumps(event)}\n\n"
            writer.write(sse_data.encode("utf-8"))
            await writer.drain()

        writer.write(b"data: [DONE]\n\n")
        await writer.drain()
    except (ConnectionResetError, BrokenPipeError, ConnectionError):
        cancel_event.set()
        agent_task.cancel()
    finally:
        if not agent_task.done():
            cancel_event.set()
            agent_task.cancel()


async def start_server(host: str = "127.0.0.1", port: int = 4096) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"⚠️  WARNING: Binding server to non-loopback host {host}. Ensure firewall is active!", file=sys.stderr)

    token = get_server_token()
    server = await asyncio.start_server(handle_request, host, port)
    print(f"✓ VALLEN CLI REST/SSE server listening on http://{host}:{port}")
    print(f"  Auth Token : {token}")
    print(f"  Authorization Header: Bearer {token}")
    print(f"  GET  http://{host}:{port}/health")
    print(f"  GET  http://{host}:{port}/models")
    print(f"  POST http://{host}:{port}/chat (SSE Stream)")
    async with server:
        await server.serve_forever()
