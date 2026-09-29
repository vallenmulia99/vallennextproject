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
import json
import sys
import urllib.parse
from typing import Any

from .config import get_config
from .workspace import get_workspace
from .session import get_session_manager
from ..providers.registry import get_registry
from .agent import run_agent, AgentEvent


async def handle_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        line = await reader.readline()
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
            hline = await reader.readline()
            if not hline or hline in (b"\r\n", b"\n"):
                break
            header_str = hline.decode(errors="replace").strip()
            if ":" in header_str:
                k, _, v = header_str.partition(":")
                headers[k.strip().lower()] = v.strip()

        # Read body if Content-Length given
        body_bytes = b""
        if "content-length" in headers:
            length = int(headers["content-length"])
            body_bytes = await reader.readexactly(length)

        # Route requests
        if method == "GET" and path in ("/health", "/"):
            response_data = json.dumps({"status": "ok", "app": "vallen-cli", "version": "0.1.0"})
            _send_json(writer, 200, response_data)
            return

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
            _send_json(writer, 200, json.dumps({"models": models}))
            return

        if method == "GET" and path == "/sessions":
            sess_mgr = get_session_manager()
            sessions = sess_mgr.list_all_for_project()
            _send_json(writer, 200, json.dumps({"sessions": sessions}))
            return

        if method == "POST" and path == "/chat":
            await _handle_chat_sse(writer, body_bytes)
            return

        # 404 fallback
        _send_json(writer, 404, json.dumps({"error": "Not found"}))
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


def _send_json(writer: asyncio.StreamWriter, status_code: int, json_str: str) -> None:
    status_text = {200: "OK", 400: "Bad Request", 404: "Not Found", 500: "Internal Server Error"}.get(status_code, "OK")
    body = json_str.encode("utf-8")
    headers = [
        f"HTTP/1.1 {status_code} {status_text}",
        "Content-Type: application/json",
        f"Content-Length: {len(body)}",
        "Access-Control-Allow-Origin: *",
        "Connection: close",
        "",
        "",
    ]
    writer.write("\r\n".join(headers).encode("utf-8") + body)


async def _handle_chat_sse(writer: asyncio.StreamWriter, body_bytes: bytes) -> None:
    try:
        payload = json.loads(body_bytes.decode(errors="replace"))
    except Exception:
        _send_json(writer, 400, json.dumps({"error": "Invalid JSON body"}))
        return

    prompt = payload.get("prompt", "")
    if not prompt:
        _send_json(writer, 400, json.dumps({"error": "prompt is required"}))
        return

    project = payload.get("project", "")
    if project:
        ws = get_workspace()
        ws.set_active_project(project)

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
        "Access-Control-Allow-Origin: *",
        "",
        "",
    ]
    writer.write("\r\n".join(headers).encode("utf-8"))
    await writer.drain()

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def on_event(ev: AgentEvent) -> None:
        queue.put_nowait({"kind": ev.kind, "data": ev.data})

    async def run_task():
        try:
            res = await run_agent(prompt, on_event=on_event)
            queue.put_nowait({"kind": "done", "data": res})
        except Exception as err:
            queue.put_nowait({"kind": "error", "data": str(err)})
        finally:
            queue.put_nowait(None)

    asyncio.create_task(run_task())

    while True:
        event = await queue.get()
        if event is None:
            break
        sse_data = f"data: {json.dumps(event)}\n\n"
        writer.write(sse_data.encode("utf-8"))
        await writer.drain()

    writer.write(b"data: [DONE]\n\n")
    await writer.drain()


async def start_server(host: str = "127.0.0.1", port: int = 4096) -> None:
    server = await asyncio.start_server(handle_request, host, port)
    print(f"✓ VALLEN CLI REST/SSE server listening on http://{host}:{port}")
    print(f"  GET  http://{host}:{port}/health")
    print(f"  GET  http://{host}:{port}/models")
    print(f"  POST http://{host}:{port}/chat (SSE Stream)")
    async with server:
        await server.serve_forever()
