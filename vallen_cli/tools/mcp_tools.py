"""VALLEN CLI — MCP Resource tools.

Mirrors OpenCode session/tools.ts:
- list_mcp_resources: lists available resources from connected MCP servers
- read_mcp_resource: reads the text/content of a specific MCP resource URI
"""

from __future__ import annotations

import json
from typing import Any

from .base import BaseTool, ToolResult
from ..core.mcp import get_mcp_manager


class ListMcpResourcesTool(BaseTool):
    name = "list_mcp_resources"
    description = (
        "Lists available resources provided by connected MCP (Model Context Protocol) servers. "
        "Returns resource URIs, names, and mime types."
    )
    parameters = {
        "type": "object",
        "properties": {
            "server": {
                "type": "string",
                "description": "Optional server name to filter resources",
            },
        },
    }

    async def execute(self, server: str = "", **kwargs: Any) -> ToolResult:
        mgr = get_mcp_manager()
        resources = mgr.all_resources()

        if server:
            resources = [r for r in resources if r.get("server") == server]

        if not resources:
            return ToolResult(
                success=True,
                output="No MCP resources available. Connect MCP servers in ~/.config/vallen/config.toml under [mcp.servers].",
            )

        lines = [f"Available MCP Resources ({len(resources)}):\n"]
        for r in resources:
            s_name = r.get("server", "unknown")
            uri = r.get("uri", "")
            name = r.get("name", "")
            mime = r.get("mimeType", "")
            lines.append(f"  • [{s_name}] {name or uri}")
            lines.append(f"    URI: {uri} ({mime})")

        return ToolResult(success=True, output="\n".join(lines))


class ReadMcpResourceTool(BaseTool):
    name = "read_mcp_resource"
    description = (
        "Read a specific resource from an MCP server given the server name and resource URI."
    )
    parameters = {
        "type": "object",
        "properties": {
            "server": {
                "type": "string",
                "description": "The MCP server name hosting the resource",
            },
            "uri": {
                "type": "string",
                "description": "The resource URI to read",
            },
        },
        "required": ["server", "uri"],
    }

    async def execute(self, server: str, uri: str, **kwargs: Any) -> ToolResult:
        mgr = get_mcp_manager()
        client = mgr.get_client(server)
        if not client:
            return ToolResult(
                success=False,
                output="",
                error=f"MCP server '{server}' is not connected.",
            )

        res = await client.read_resource(uri)
        if "error" in res:
            return ToolResult(success=False, output="", error=str(res["error"]))

        contents = res.get("result", {}).get("contents", [])
        text_parts = []
        for item in contents:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    text_parts.append(text)
                elif item.get("blob"):
                    text_parts.append(f"[Binary blob ({item.get('mimeType', 'octet-stream')})]")

        output = "\n\n".join(text_parts) if text_parts else "Resource returned empty content."
        return ToolResult(success=True, output=output)
