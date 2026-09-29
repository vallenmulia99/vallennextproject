"""VALLEN CLI — Model Context Protocol (MCP) client.

Mirrors OpenCode mcp/index.ts:
Connects to external MCP servers via stdio JSON-RPC 2.0, discovers tools
and resources, and registers them into VALLEN CLI agent loop.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import get_config
from ..tools.base import BaseTool, ToolResult


@dataclass
class McpServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


class McpClient:
    """JSON-RPC 2.0 stdio client for an MCP server process."""

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._proc: asyncio.subprocess.Process | None = None
        self._req_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task | None = None
        self._tools: list[dict[str, Any]] = []
        self._resources: list[dict[str, Any]] = []

    async def start(self) -> bool:
        cmd_path = shutil.which(self.config.command) or self.config.command
        full_env = os.environ.copy()
        full_env.update(self.config.env)

        try:
            self._proc = await asyncio.create_subprocess_exec(
                cmd_path,
                *self.config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=full_env,
            )
            self._reader_task = asyncio.create_task(self._read_loop())

            # Initialize protocol handshake
            init_res = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "clientInfo": {"name": "vallen-cli", "version": "0.1.0"},
            })
            if "error" in init_res:
                await self.stop()
                return False

            # Send initialized notification
            await self._send_notification("notifications/initialized", {})

            # Fetch tools
            tools_res = await self._send_request("tools/list", {})
            self._tools = tools_res.get("result", {}).get("tools", [])

            # Fetch resources
            try:
                res_res = await self._send_request("resources/list", {})
                self._resources = res_res.get("result", {}).get("resources", [])
            except Exception:
                self._resources = []

            return True
        except Exception:
            await self.stop()
            return False

    async def _read_loop(self) -> None:
        if not self._proc or not self._proc.stdout:
            return
        while True:
            try:
                line = await self._proc.stdout.readline()
                if not line:
                    for fut in list(self._pending.values()):
                        if not fut.done():
                            fut.set_result({"error": "Process terminated / EOF"})
                    self._pending.clear()
                    break
                raw = line.decode(errors="replace").strip()
                if not raw:
                    continue
                data = json.loads(raw)
                req_id = data.get("id")
                if req_id in self._pending:
                    fut = self._pending.pop(req_id)
                    if not fut.done():
                        fut.set_result(data)
            except Exception:
                break

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._proc or not self._proc.stdin:
            return {"error": "Process not started"}

        self._req_id += 1
        rid = self._req_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut

        msg = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        payload = json.dumps(msg) + "\n"
        self._proc.stdin.write(payload.encode("utf-8"))
        await self._proc.stdin.drain()

        try:
            return await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            return {"error": f"MCP request {method} timed out"}

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        if not self._proc or not self._proc.stdin:
            return
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        payload = json.dumps(msg) + "\n"
        self._proc.stdin.write(payload.encode("utf-8"))
        await self._proc.stdin.drain()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        res = await self._send_request("tools/call", {"name": name, "arguments": arguments})
        if "error" in res:
            return {"isError": True, "content": [{"type": "text", "text": str(res["error"])}]}
        return res.get("result", {})

    async def read_resource(self, uri: str) -> dict[str, Any]:
        return await self._send_request("resources/read", {"uri": uri})

    @property
    def tools(self) -> list[dict[str, Any]]:
        return list(self._tools)

    @property
    def resources(self) -> list[dict[str, Any]]:
        return list(self._resources)

    async def stop(self) -> None:
        reader_task = self._reader_task
        self._reader_task = None
        if reader_task:
            reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await reader_task

        for fut in self._pending.values():
            if not fut.done():
                fut.set_result({"error": "MCP client stopped"})
        self._pending.clear()

        proc = self._proc
        self._proc = None
        if proc:
            try:
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
            except Exception:
                pass


class McpProxyTool(BaseTool):
    """Dynamic tool proxying calls to an external MCP server."""

    def __init__(self, client: McpClient, mcp_def: dict[str, Any]) -> None:
        self.client = client
        self.name = f"mcp__{client.config.name}__{mcp_def['name']}"
        self.aliases = [mcp_def["name"]]
        self.description = mcp_def.get("description", f"MCP Tool: {mcp_def['name']}")
        self.parameters = mcp_def.get("inputSchema", {"type": "object", "properties": {}})
        self._orig_name = mcp_def["name"]

    async def execute(self, **kwargs: Any) -> ToolResult:
        res = await self.client.call_tool(self._orig_name, kwargs)
        is_err = res.get("isError", False)
        contents = res.get("content", [])
        text_parts = []
        for part in contents:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        body = "\n".join(text_parts) if text_parts else json.dumps(res)
        if is_err:
            return ToolResult(success=False, output=body, error=body)
        return ToolResult(success=True, output=body)


class McpManager:
    """Manages all configured MCP servers and tool registrations."""

    def __init__(self) -> None:
        self._clients: dict[str, McpClient] = {}

    def load_configs(self) -> list[McpServerConfig]:
        cfg = get_config()
        mcp_section = cfg.get("mcp", default={})
        servers: list[McpServerConfig] = []
        if isinstance(mcp_section, dict):
            srv_map = mcp_section.get("servers", mcp_section)
            if isinstance(srv_map, dict):
                for name, details in srv_map.items():
                    if isinstance(details, dict) and "command" in details:
                        cmd = details["command"]
                        args = details.get("args", [])
                        if isinstance(cmd, list) and cmd:
                            args = cmd[1:] + args
                            cmd = cmd[0]
                        servers.append(McpServerConfig(
                            name=name,
                            command=str(cmd),
                            args=[str(a) for a in args],
                            env=details.get("env", {}),
                            enabled=details.get("enabled", True),
                        ))
        return servers

    async def initialize(self) -> None:
        from ..tools.registry import get_tool_registry
        reg = get_tool_registry()

        configs = self.load_configs()
        for srv_cfg in configs:
            if not srv_cfg.enabled:
                continue
            
            # Idempotency guard: skip if already running
            existing = self._clients.get(srv_cfg.name)
            if existing is not None and existing._proc is not None and existing._proc.returncode is None:
                continue  # Already running, skip spawn
            if existing is not None:
                await existing.stop()

            client = McpClient(srv_cfg)
            ok = await client.start()
            if ok:
                self._clients[srv_cfg.name] = client
                for tool_def in client.tools:
                    proxy = McpProxyTool(client, tool_def)
                    reg.register(proxy)

    def add_server(self, name: str, command: str, args: list[str] | None = None, env: dict[str, str] | None = None) -> bool:
        cfg = get_config()
        cfg.load()
        mcp_sec = cfg.get("mcp", default={})
        if not isinstance(mcp_sec, dict):
            mcp_sec = {}
        servers = mcp_sec.get("servers", mcp_sec) if "servers" in mcp_sec else mcp_sec
        servers[name] = {
            "command": command,
            "args": args or [],
            "env": env or {},
            "enabled": True,
        }
        cfg.set("mcp", "servers", servers)
        cfg.save()
        return True

    def remove_server(self, name: str) -> bool:
        cfg = get_config()
        cfg.load()
        mcp_sec = cfg.get("mcp", default={})
        servers = mcp_sec.get("servers", mcp_sec) if isinstance(mcp_sec, dict) and "servers" in mcp_sec else mcp_sec
        if isinstance(servers, dict) and name in servers:
            del servers[name]
            cfg.set("mcp", "servers", servers)
            cfg.save()
            if name in self._clients:
                client = self._clients.pop(name)
                try:
                    asyncio.create_task(client.stop())
                except Exception:
                    pass
            return True
        return False

    def list_status(self) -> list[dict[str, Any]]:
        configs = self.load_configs()
        results = []
        for c in configs:
            client = self._clients.get(c.name)
            is_running = client is not None and client._proc is not None and client._proc.returncode is None
            results.append({
                "name": c.name,
                "command": c.command,
                "args": c.args,
                "enabled": c.enabled,
                "running": is_running,
                "tools": len(client.tools) if client else 0,
                "resources": len(client.resources) if client else 0,
            })
        return results

    def get_client(self, name: str) -> McpClient | None:
        return self._clients.get(name)

    def all_resources(self) -> list[dict[str, Any]]:
        results = []
        for srv_name, client in self._clients.items():
            for r in client.resources:
                item = dict(r)
                item["server"] = srv_name
                results.append(item)
        return results

    async def stop_all(self) -> None:
        for client in self._clients.values():
            await client.stop()
        self._clients.clear()


_mcp_mgr: McpManager | None = None


def get_mcp_manager() -> McpManager:
    global _mcp_mgr
    if _mcp_mgr is None:
        _mcp_mgr = McpManager()
    return _mcp_mgr
