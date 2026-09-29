"""VALLEN CLI — Web Extract Tool (inspired by Hermes web_extract).

Extracts clean article content from URLs in markdown/text with head+tail truncation
and scratch-file caching for long documents.
"""

from __future__ import annotations

import re
import html
from typing import Any
import httpx

from .base import BaseTool, ToolResult
from ..core.scratch import save_scratch_file

_DEFAULT_CHAR_LIMIT = 15000


def html_to_clean_markdown(raw_html: str) -> str:
    """Convert raw HTML into clean, readable Markdown without noise."""
    text = raw_html

    # Remove script, style, head, noscript, svg, nav, footer tags
    text = re.sub(r"<(script|style|head|noscript|svg|nav|footer)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    # Convert headings
    text = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<h[4-6][^>]*>(.*?)</h[4-6]>", r"\n#### \1\n", text, flags=re.DOTALL | re.IGNORECASE)

    # Convert code blocks and pre
    text = re.sub(r"<pre[^>]*><code[^>]*>(.*?)</code></pre>", r"\n```\n\1\n```\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.DOTALL | re.IGNORECASE)

    # Convert paragraphs and breaks
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", text, flags=re.DOTALL | re.IGNORECASE)

    # Convert links
    text = re.sub(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", text, flags=re.DOTALL | re.IGNORECASE)

    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Unescape HTML entities
    text = html.unescape(text)

    # Clean whitespace: collapse 3+ newlines to 2, collapse multiple spaces
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


class WebExtractTool(BaseTool):
    name = "web_extract"
    aliases = ["extract_web", "fetch_page"]
    description = (
        "Extract clean, readable content from web page URLs in Markdown format. "
        "Pages within character budget return whole; larger pages return head+tail with scratch cache."
    )
    parameters = {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of URLs to extract content from (max 5 URLs per call)",
            },
            "char_limit": {
                "type": "integer",
                "description": f"Maximum characters to return inline (default {_DEFAULT_CHAR_LIMIT})",
            },
        },
        "required": ["urls"],
    }

    async def execute(
        self,
        urls: list[str] | str = "",
        char_limit: int = _DEFAULT_CHAR_LIMIT,
        **kwargs: Any,
    ) -> ToolResult:
        url_list = [urls] if isinstance(urls, str) else list(urls)
        if not url_list:
            return ToolResult(success=False, output="", error="urls parameter is required")

        limit = min(max(1000, int(char_limit or _DEFAULT_CHAR_LIMIT)), 50000)
        results: list[str] = []

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,text/plain,*/*",
        }

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            for u in url_list[:5]:
                if not u.startswith(("http://", "https://")):
                    results.append(f"### {u}\nError: URL must start with http:// or https://")
                    continue
                try:
                    resp = await client.get(u)
                    if resp.status_code >= 400:
                        results.append(f"### {u}\nError: HTTP {resp.status_code} ({resp.reason_phrase})")
                        continue

                    clean_md = html_to_clean_markdown(resp.text)
                    if len(clean_md) <= limit:
                        results.append(f"### [{u}]\n\n{clean_md}")
                    else:
                        scratch_path = save_scratch_file(clean_md, prefix="web_extract")
                        head_size = int(limit * 0.7)
                        tail_size = int(limit * 0.25)
                        head = clean_md[:head_size]
                        tail = clean_md[-tail_size:]
                        clipped = (
                            f"{head}\n\n... [Content truncated ({len(clean_md):,} chars total). "
                            f"Full text cached to {scratch_path}. Use read tool with offset/limit to page through.] ...\n\n{tail}"
                        )
                        results.append(f"### [{u}]\n\n{clipped}")
                except Exception as exc:
                    results.append(f"### {u}\nFetch error: {exc}")

        return ToolResult(
            success=True,
            output="\n\n---\n\n".join(results),
        )
