"""VALLEN CLI — WebSearch Tool.

Mirrors OpenCode websearch.ts:
Performs real-time web searches to retrieve up-to-date information,
documentation, library usages, and bug fixes beyond model training cutoff.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import urllib.parse
from typing import Any

import httpx

from .base import BaseTool, ToolResult


class WebSearchTool(BaseTool):
    name = "websearch"
    _description_template = "- Search the web using the session's web search provider - performs real-time web searches and can scrape content from specific URLs\n- Provides up-to-date information for current events and recent data\n- Supports configurable result counts and returns the content from the most relevant websites\n- Use this tool for accessing information beyond knowledge cutoff\n- Searches are performed automatically within a single API call\n\nUsage notes:\n  - Supports live crawling modes when available: 'fallback' (backup if cached unavailable) or 'preferred' (prioritize live crawling)\n  - Search types when available: 'auto' (balanced), 'fast' (quick results), 'deep' (comprehensive search)\n  - Configurable context length for optimal LLM integration\n  - Domain filtering and advanced search options available\n\nThe current year is {{year}}. You MUST use this year when searching for recent information or current events\n- Example: If the current year is {{year}} and the user asks for \"latest AI news\", search for \"AI news {{year}}\", NOT \"AI news {{year_minus_1}}\""
    
    @property
    def description(self) -> str:
        """Substitute {{year}} placeholder with current year."""
        year = datetime.datetime.now().year
        return self._description_template.replace("{{year}}", str(year)).replace("{{year_minus_1}}", str(year - 1))
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up on the web",
            },
            "numResults": {
                "type": "integer",
                "description": "Number of search results to return (default: 8)",
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        query: str,
        numResults: int = 8,
        **kwargs: Any,
    ) -> ToolResult:
        q = (query or "").strip()
        if not q:
            return ToolResult(success=False, output="", error="query is required")

        limit = min(max(1, int(numResults or 8)), 15)

        # 1. Check Tavily API if configured
        tavily_key = os.environ.get("TAVILY_API_KEY")
        if tavily_key:
            res = await self._search_tavily(q, tavily_key, limit)
            if res:
                return ToolResult(success=True, output=res)

        # 2. Check Exa API if configured
        exa_key = os.environ.get("EXA_API_KEY")
        if exa_key:
            res = await self._search_exa(q, exa_key, limit)
            if res:
                return ToolResult(success=True, output=res)

        # 3. Universal DuckDuckGo HTML / Lite search
        res = await self._search_ddg(q, limit)
        if res:
            return ToolResult(success=True, output=res)

        return ToolResult(
            success=False,
            output="",
            error=f"No results found for query: '{q}'. Try rephrasing or check internet connection.",
        )

    async def _search_ddg(self, query: str, limit: int) -> str | None:
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        data = {"q": query}

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.post(url, data=data, headers=headers)
                if resp.status_code != 200:
                    return None

                html = resp.text

                # Parse search results
                # DDG html structure: <a class="result__snippet" ...>...</a>
                # and <a class="result__url" ...>...</a>
                results = []
                blocks = re.findall(
                    r'<a[^>]+class="result__url"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
                    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                    html,
                    re.DOTALL | re.IGNORECASE,
                )

                if not blocks:
                    # Alternative block pattern
                    blocks_alt = re.findall(
                        r'<h2 class="result__title">.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?</h2>.*?'
                        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                        html,
                        re.DOTALL | re.IGNORECASE,
                    )
                    blocks = blocks_alt

                for href, title, snippet in blocks[:limit]:
                    # Clean DuckDuckGo redirect url
                    clean_url = href
                    if "/l/?kh=-1&uddg=" in href:
                        match = re.search(r'uddg=([^&]+)', href)
                        if match:
                            clean_url = urllib.parse.unquote(match.group(1))

                    clean_title = re.sub(r'<[^>]+>', '', title).strip()
                    clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()

                    if clean_url and clean_title:
                        results.append({
                            "title": clean_title,
                            "url": clean_url,
                            "snippet": clean_snippet,
                        })

                if not results:
                    return None

                lines = [f"Web Search Results for: '{query}' (Found {len(results)}):\n"]
                for i, r in enumerate(results, start=1):
                    lines.append(f"{i}. {r['title']}")
                    lines.append(f"   URL: {r['url']}")
                    if r['snippet']:
                        lines.append(f"   {r['snippet']}")
                    lines.append("")

                return "\n".join(lines).strip()
        except Exception:
            return None

    async def _search_tavily(self, query: str, api_key: str, limit: int) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    "https://api.tavily.com/search",
                    json={"query": query, "api_key": api_key, "max_results": limit},
                )
                if r.status_code != 200:
                    return None
                data = r.json()
                items = data.get("results", [])
                if not items:
                    return None
                lines = [f"Web Search Results for: '{query}':\n"]
                for i, item in enumerate(items, start=1):
                    lines.append(f"{i}. {item.get('title', '')}")
                    lines.append(f"   URL: {item.get('url', '')}")
                    lines.append(f"   {item.get('content', '')}")
                    lines.append("")
                return "\n".join(lines).strip()
        except Exception:
            return None

    async def _search_exa(self, query: str, api_key: str, limit: int) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    "https://api.exa.ai/search",
                    headers={"x-api-key": api_key, "Content-Type": "application/json"},
                    json={"query": query, "numResults": limit},
                )
                if r.status_code != 200:
                    return None
                data = r.json()
                items = data.get("results", [])
                if not items:
                    return None
                lines = [f"Web Search Results for: '{query}':\n"]
                for i, item in enumerate(items, start=1):
                    lines.append(f"{i}. {item.get('title', '')}")
                    lines.append(f"   URL: {item.get('url', '')}")
                    if item.get("text"):
                        lines.append(f"   {item.get('text', '')[:300]}...")
                    lines.append("")
                return "\n".join(lines).strip()
        except Exception:
            return None
