"""VALLEN CLI — Agent interaction tools.

Inspired by opencode/src/tool/todo.ts and question.ts.

1. todowrite  — agent writes/updates a task list (visible in TUI)
2. question   — agent asks user questions, pauses until answered
3. webfetch   — fetch a URL and return markdown/text content
4. glob       — find files matching a glob pattern
"""

from __future__ import annotations

import asyncio
import fnmatch
import re
from pathlib import Path
from typing import Any

import httpx

from .base import BaseTool, ToolResult
from ..core.workspace import get_workspace


# ===========================================================================
# todowrite — agent task tracker
# ===========================================================================

# In-memory todo state per session (keyed by session_id or global)
_todo_state: list[dict[str, Any]] = []

TODO_STATUSES = {"pending", "in_progress", "completed"}
TODO_PRIORITIES = {"high", "medium", "low"}


def get_todos() -> list[dict[str, Any]]:
    return list(_todo_state)


def set_todos(todos: list[dict[str, Any]]) -> None:
    global _todo_state
    _todo_state = list(todos)


class TodoWriteTool(BaseTool):
    name = "todowrite"
    description = "Create and maintain a structured task list for the current coding session. Tracks progress, organizes multi-step work, and surfaces status to the user.\n\n## When to use\nUse proactively when:\n- The task requires 3+ distinct steps or actions (not just 3 tool calls for a single conceptual step)\n- The work is non-trivial and benefits from planning\n- The user provides multiple tasks (numbered or comma-separated) or explicitly asks for a todo list\n- New instructions arrive - capture them as todos\n- You start a task - mark it `in_progress` (only one at a time) before working\n- You finish a task - mark it `completed` and add any follow-ups discovered during the work\n\n## When NOT to use\nSkip when:\n- The work is a single, straightforward task (or <3 trivial steps)\n- The request is purely informational or conversational\n- Tracking adds no organizational value\n\n## States\n- `pending` - not started\n- `in_progress` - actively working (exactly ONE at a time)\n- `completed` - finished successfully\n- `cancelled` - no longer needed\n\n## Rules\n- Update status in real time; don't batch completions\n- Mark `completed` only after the required work is actually done, including any required verification. Never based on intent.\n- Keep exactly one `in_progress` while work remains\n- If blocked or partial, keep it `in_progress` and add a follow-up todo describing the blocker\n- Preserve user-provided commands verbatim (flags, args, order)\n- Items should be specific and actionable; break large work into smaller steps\n\n## Examples\n\nUse it:\n- \"Add a dark mode toggle and run the tests\" -> multi-step feature + explicit verification\n- \"Rename getCwd -> getCurrentWorkingDirectory across the repo\" -> grep reveals 15 occurrences in 8 files\n- \"Implement registration, catalog, cart, checkout\" -> multiple complex features\n\nSkip it:\n- \"How do I print Hello World in Python?\" -> informational\n- \"Add a comment to calculateTotal\" -> single edit\n- \"Run npm install and tell me what happened\" -> one command\n\nWhen in doubt, use it."
    parameters = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "The complete updated todo list",
                "items": {
                    "type": "object",
                    "properties": {
                        "content":  {"type": "string",  "description": "Task description"},
                        "status":   {"type": "string",  "enum": ["pending", "in_progress", "completed"]},
                        "priority": {"type": "string",  "enum": ["high", "medium", "low"]},
                        "id":       {"type": "string",  "description": "Unique task ID (optional)"},
                    },
                    "required": ["content", "status", "priority"],
                },
            }
        },
        "required": ["todos"],
    }

    async def execute(self, todos: list[dict[str, Any]], **kwargs: Any) -> ToolResult:  # type: ignore[override]
        if not isinstance(todos, list):
            return ToolResult(success=False, output="", error="todos must be a list")

        cleaned: list[dict[str, Any]] = []
        for i, t in enumerate(todos):
            status = t.get("status", "pending")
            priority = t.get("priority", "medium")
            if status not in TODO_STATUSES:
                status = "pending"
            if priority not in TODO_PRIORITIES:
                priority = "medium"
            cleaned.append({
                "id": t.get("id", str(i + 1)),
                "content": str(t.get("content", "")),
                "status": status,
                "priority": priority,
            })

        set_todos(cleaned)

        pending   = sum(1 for t in cleaned if t["status"] == "pending")
        active    = sum(1 for t in cleaned if t["status"] == "in_progress")
        done      = sum(1 for t in cleaned if t["status"] == "completed")
        total     = len(cleaned)

        # Build display output
        icons = {"pending": "○", "in_progress": "◌", "completed": "✓"}
        lines = [f"Tasks ({done}/{total} done)\n"]
        for t in cleaned:
            icon = icons.get(t["status"], "○")
            pri  = f"[{t['priority']}]" if t["priority"] == "high" else ""
            lines.append(f"  {icon} {t['content']} {pri}".rstrip())

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"todos": cleaned, "pending": pending, "active": active, "done": done},
        )


# ===========================================================================
# question — agent asks user a question, blocks until answered
# ===========================================================================

# Global pending question state — TUI polls this
_pending_question: dict[str, Any] | None = None
_question_answer: asyncio.Future | None = None
_question_ask_callback = None  # set by TUI on mount


def get_pending_question() -> dict[str, Any] | None:
    return _pending_question


async def answer_question(answer: str) -> None:
    global _pending_question, _question_answer
    if _question_answer and not _question_answer.done():
        _question_answer.set_result(answer)
    _pending_question = None


class QuestionTool(BaseTool):
    name = "question"
    description = "Use this tool when you need to ask the user questions during execution. This allows you to:\n1. Gather user preferences or requirements\n2. Clarify ambiguous instructions\n3. Get decisions on implementation choices as you work\n4. Offer choices to the user about what direction to take.\n\nUsage notes:\n- When `custom` is enabled (default), a \"Type your own answer\" option is added automatically; don't include \"Other\" or catch-all options\n- Answers are returned as arrays of labels; set `multiple: true` to allow selecting more than one\n- If you recommend a specific option, make that the first option in the list and add \"(Recommended)\" at the end of the label"
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask the user",
            },
            "options": {
                "type": "array",
                "description": "Optional list of choices for the user to pick from",
                "items": {"type": "string"},
            },
        },
        "required": ["question"],
    }

    async def execute(self, question: str, options: list[str] | None = None, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        global _pending_question, _question_answer

        if not question.strip():
            return ToolResult(success=False, output="", error="question is empty")

        # Use TUI modal callback if available
        if _question_ask_callback is not None:
            try:
                answer = await _question_ask_callback(question, options or [])
                return ToolResult(
                    success=True,
                    output=f"User answered: {answer}",
                    data={"question": question, "answer": answer},
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Question error: {e}")

        # In web / headless mode without an interactive callback, prompt agent to ask in chat
        return ToolResult(
            success=True,
            output=(
                f"Interactive prompt unavailable. Please include your question directly in your "
                f"chat response to the user so they can answer: '{question}'"
            ),
            data={"question": question},
        )


# ===========================================================================
# webfetch — fetch a URL → markdown / plain text
# ===========================================================================

_MAX_BYTES = 2 * 1024 * 1024   # 2 MB
_TIMEOUT   = 30.0


def _html_to_text(html: str) -> str:
    """Strip HTML tags, return plain text."""
    # Remove scripts/styles
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace block-level tags with newlines
    html = re.sub(r"<(br|p|div|h[1-6]|li|tr)[^>]*>", "\n", html, flags=re.IGNORECASE)
    # Remove all remaining tags
    html = re.sub(r"<[^>]+>", "", html)
    # Decode common entities
    for entity, char in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                          ("&nbsp;", " "), ("&quot;", '"'), ("&#39;", "'")]:
        html = html.replace(entity, char)
    # Collapse whitespace
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def _html_to_markdown(html: str) -> str:
    """Very lightweight HTML → Markdown (no external deps)."""
    # Headings
    for n in range(6, 0, -1):
        html = re.sub(rf"<h{n}[^>]*>(.*?)</h{n}>", lambda m, n=n: "\n" + "#" * n + " " + m.group(1).strip() + "\n", html, flags=re.DOTALL | re.IGNORECASE)
    # Bold / italic
    html = re.sub(r"<(strong|b)[^>]*>(.*?)</\1>", r"**\2**", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<(em|i)[^>]*>(.*?)</\1>", r"*\2*",   html, flags=re.DOTALL | re.IGNORECASE)
    # Code
    html = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<pre[^>]*>(.*?)</pre>",   lambda m: "\n```\n" + m.group(1).strip() + "\n```\n", html, flags=re.DOTALL | re.IGNORECASE)
    # Links
    html = re.sub(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r"[\2](\1)", html, flags=re.DOTALL | re.IGNORECASE)
    # Lists
    html = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", html, flags=re.DOTALL | re.IGNORECASE)
    # Remaining tags → plain text
    return _html_to_text(html)


class WebFetchTool(BaseTool):
    name = "webfetch"
    description = "- Fetches content from a specified URL\n- Takes a URL and optional format as input\n- Fetches the URL content, converts to requested format (markdown by default)\n- Returns the content in the specified format\n- Use this tool when you need to retrieve and analyze web content\n\nUsage notes:\n  - IMPORTANT: if another tool is present that offers better web fetching capabilities, is more targeted to the task, or has fewer restrictions, prefer using that tool instead of this one.\n  - The URL must be a fully-formed valid URL\n  - HTTP URLs will be automatically upgraded to HTTPS\n  - Format options: \"markdown\" (default), \"text\", or \"html\"\n  - This tool is read-only and does not modify any files\n  - Results may be summarized if the content is very large"
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch (must start with http:// or https://)",
            },
            "format": {
                "type": "string",
                "enum": ["markdown", "text", "raw"],
                "description": "Output format: markdown (default), text, or raw HTML",
            },
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds (default 30, max 120)",
            },
        },
        "required": ["url"],
    }

    async def execute(  # type: ignore[override]
        self,
        url: str,
        format: str = "markdown",
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> ToolResult:
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, output="", error="URL must start with http:// or https://")

        actual_timeout = min(float(timeout or 30), 120.0)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,text/plain,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(actual_timeout),
                headers=headers,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

                raw = resp.content
                if len(raw) > _MAX_BYTES:
                    raw = raw[:_MAX_BYTES]

                content_type = resp.headers.get("content-type", "").lower()
                text = raw.decode(errors="replace")

                if format == "raw":
                    output = text[:50_000]
                elif "text/html" in content_type and format == "markdown":
                    output = _html_to_markdown(text)[:50_000]
                elif "text/html" in content_type:
                    output = _html_to_text(text)[:50_000]
                else:
                    output = text[:50_000]

                return ToolResult(
                    success=True,
                    output=output,
                    data={"url": url, "status": resp.status_code, "content_type": content_type},
                )

        except httpx.TimeoutException:
            return ToolResult(success=False, output="", error=f"Request timed out after {actual_timeout}s")
        except httpx.HTTPStatusError as e:
            return ToolResult(success=False, output="", error=f"HTTP {e.response.status_code}: {url}")
        except httpx.ConnectError:
            return ToolResult(success=False, output="", error=f"Cannot connect to: {url}")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Fetch error: {e}")


# ===========================================================================
# glob — pattern-based file search
# ===========================================================================

class GlobTool(BaseTool):
    name = "glob"
    description = "- Fast file pattern matching tool that works with any codebase size\n- Supports glob patterns like \"**/*.js\" or \"src/**/*.ts\"\n- Returns matching file paths\n- Use this tool when you need to find files by name patterns\n- When you are doing an open-ended search that may require multiple rounds of globbing and grepping, use the Task tool instead\n- You have the capability to call multiple tools in a single response. It is always better to speculatively perform multiple searches as a batch that are potentially useful."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match files against (e.g. '**/*.py', 'src/*.ts')",
            },
            "path": {
                "type": "string",
                "description": "Root directory to search from (default: project root)",
            },
            "limit": {
                "type": "integer",
                "description": "Max files to return (default 200)",
            },
        },
        "required": ["pattern"],
    }

    # Dirs to always skip
    IGNORED = {
        ".git", "__pycache__", "node_modules", ".venv", "venv",
        ".mypy_cache", ".pytest_cache", "dist", "build", ".tox",
        ".eggs", ".next", ".nuxt", "coverage", ".coverage",
    }

    async def execute(  # type: ignore[override]
        self,
        pattern: str = "*",
        path: str = "",
        filePath: str = "",
        limit: int = 200,
        **kwargs: Any,
    ) -> ToolResult:
        ws = get_workspace()
        # Accept `root` as a compatibility alias used by several OpenCode-style
        # clients, while keeping `path` as the documented parameter.
        search_path = path or filePath or kwargs.get("root", "") or kwargs.get("directory", "")
        from ..core.workspace import resolve_workspace_path
        try:
            root = resolve_workspace_path(search_path or ".")
        except PermissionError as e:
            return ToolResult(success=False, output="", error=str(e))

        if not root.exists():
            return ToolResult(success=False, output="", error=f"Path not found: {root}")

        limit = min(max(1, limit), 1000)

        try:
            matches: list[str] = []

            def _scan() -> list[str]:
                found: list[str] = []
                # Use Path.glob which respects path separators (* vs **)
                for p in root.glob(pattern):
                    # Skip ignored dirs
                    if any(part in self.IGNORED for part in p.parts):
                        continue
                    if not p.is_file():
                        continue
                    rel = str(p.relative_to(root))
                    found.append(rel)
                    if len(found) >= limit:
                        break
                return sorted(found)

            matches = await asyncio.to_thread(_scan)

            if not matches:
                return ToolResult(
                    success=True,
                    output=f"No files matching '{pattern}' in {root}",
                    data={"matches": [], "count": 0},
                )

            truncated = len(matches) >= limit
            header = f"Found {len(matches)} file(s) matching '{pattern}'"
            if truncated:
                header += f" (showing first {limit})"
            output = header + "\n\n" + "\n".join(matches)

            return ToolResult(
                success=True,
                output=output,
                data={"matches": matches, "count": len(matches), "truncated": truncated},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=f"Glob error: {e}")
