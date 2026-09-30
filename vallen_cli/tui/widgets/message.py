"""VALLEN CLI — Chat message widget with Starry Loader & Live Effects."""

from __future__ import annotations

import re
import time
from typing import ClassVar

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import Markdown, CodeBlock
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


# Colour palette
C_YOU           = "bold #b0a0ff"      # user label
C_VALLEN_CROWN  = "bold #FFD700"      # crown gold
C_VALLEN_LBL    = "bold #b0a0ff"      # assistant label
C_TEXT          = "#f0f0f5"           # main body text
C_SYSTEM        = "#f0f0f5"           # system/info messages
C_TOOL_LBL      = "bold #66dd88"      # tool name
C_TOOL_OUT      = "#c8f0c8"           # tool output
C_ERROR         = "#ff8888"           # error text
C_STREAM        = "#e8e8ff"           # streaming buffer

# Celestial Star Animations
STAR_CYCLES = ["|", "/", "-", "\\"]
STAR_COLORS = ["#FFD700", "#F59E0B", "#FBBF24", "#38bdf8", "#818cf8", "#c084fc"]
STAR_CURSORS = [" |", " /", " -", " \\"]

TAGLINES = [
    "Weaving code & logic...",
    "Exploring symbols & context...",
    "Synthesizing architecture...",
    "Aligning AST tokens...",
    "Formulating solution...",
]

def _render_content(role: str, content: str) -> list[Widget]:
    if role == "user":
        return [
            Static(Text("  you", style=C_YOU)),
            Static(Text(f"  {content}", style=C_TEXT), classes="msg-user"),
        ]

    if role == "assistant":
        header = Text("  ")
        header.append("👑", style=C_VALLEN_CROWN)
        header.append(" vallen", style=C_VALLEN_LBL)  # Add space before vallen to prevent character spacing
        from rich.markdown import Markdown
        try:
            md = Markdown(content.strip(), code_theme="monokai")
            return [Static(header), Static(md, classes="msg-assistant")]
        except Exception:
            parts = _split_code_blocks(content)
            widgets: list[Widget] = [Static(header)]
            for kind, payload in parts:
                if kind == "code":
                    lang, code = payload  # type: ignore[misc]
                    try:
                        syn = Syntax(
                            code,
                            lang or "text",
                            theme="monokai",
                            word_wrap=True,
                            background_color="#111118",
                        )
                        widgets.append(Static(syn, classes="code-block"))
                    except Exception:
                        widgets.append(Static(Text(code, style=C_TEXT), classes="code-block"))
                else:
                    text_str = payload  # type: ignore[assignment]
                    if text_str.strip():
                        widgets.append(Static(Text(f"  {text_str}", style=C_TEXT), classes="msg-assistant"))
            return widgets

    if role == "tool":
        lines = content.split("\n", 1)
        label = lines[0] if lines else "tool"
        body = (lines[1] if len(lines) > 1 else content).strip()
        out: list[Widget] = [
            Static(Text(f"  ◆ {label}", style=C_TOOL_LBL)),
        ]
        if body:
            out.append(Static(Text(f"  {body[:2000]}", style=C_TOOL_OUT), classes="msg-tool"))
        return out

    if role == "error":
        return [Static(Text(f"  ERROR: {content}", style=C_ERROR), classes="msg-error")]

    if role == "system_info":
        return [Static(Text(f"  {content}", style=C_SYSTEM), classes="msg-system")]

    return [Static(Text(content, style=C_TEXT))]


def _split_code_blocks(text: str) -> list[tuple[str, object]]:
    pattern = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
    parts: list[tuple[str, object]] = []
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            parts.append(("text", text[last : m.start()]))
        parts.append(("code", (m.group(1), m.group(2))))
        last = m.end()
    if last < len(text):
        parts.append(("text", text[last:]))
    return parts


class ChatMessage(Widget):
    DEFAULT_CSS = """
    ChatMessage {
        height: auto;
        width: 1fr;
        margin: 0 0 1 0;
    }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = set()

    def __init__(self, role: str, content: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._role = role
        self._content = content

    def compose(self) -> ComposeResult:
        for w in _render_content(self._role, self._content):
            yield w


class StreamingMessage(Widget):
    """Accumulates streaming tokens and reasoning thoughts with live starry animation."""

    DEFAULT_CSS = """
    StreamingMessage {
        height: auto;
        width: 1fr;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._buffer = ""
        self._reasoning = ""
        self._start_time = time.time()
        self._frame = 0
        self._timer = None
        self._has_tokens = False
        self._has_reasoning = False
        self._last_stream_update = 0.0

        self._static_header: Static | None = None
        self._static_loader: Static | None = None
        self._static_reasoning: Static | None = None
        self._static_content: Static | None = None

    def compose(self) -> ComposeResult:
        header = Text("  ")
        header.append("", style=C_VALLEN_CROWN)
        header.append("vallen", style=C_VALLEN_LBL)
        self._static_header = Static(header)
        yield self._static_header

        self._static_loader = Static("", id="stream-loader")
        yield self._static_loader

        self._static_reasoning = Static("", id="stream-reasoning")
        yield self._static_reasoning

        self._static_content = Static("", id="stream-content")
        yield self._static_content

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.1, self._tick)

    def _tick(self) -> None:
        self._frame += 1
        elapsed = time.time() - self._start_time

        # 1. While waiting for response (Starry Celestial Loading)
        if not self._has_tokens and not self._has_reasoning:
            stars = STAR_CYCLES[self._frame % len(STAR_CYCLES)]
            color = STAR_COLORS[self._frame % len(STAR_COLORS)]
            phrase = TAGLINES[(self._frame // 15) % len(TAGLINES)]

            msg = Text("  ")
            msg.append(stars, style=f"bold {color}")
            msg.append(f"  {phrase} ", style="italic #d8d8f0")
            msg.append(f"[{elapsed:.1f}s]", style="#6b7280")
            if self._static_loader:
                self._static_loader.update(msg, layout=False)

        # 2. Pulsing star cursor while tokens are actively streaming
        elif self._has_tokens and not self._is_finalized():
            self._flush_stream_content()

    def _is_finalized(self) -> bool:
        return self._timer is None

    def _flush_stream_content(self) -> None:
        if self._static_content and not self._is_finalized():
            display = self._buffer[-4000:]
            cursor = STAR_CURSORS[self._frame % len(STAR_CURSORS)]
            text_obj = Text(f"  {display}", style=C_STREAM)
            text_obj.append(cursor, style=f"bold {STAR_COLORS[self._frame % len(STAR_COLORS)]}")
            self._static_content.update(text_obj, layout=False)

    def _flush_reasoning_content(self) -> None:
        if self._static_reasoning and not self._is_finalized():
            display = self._reasoning[-800:]
            elapsed = time.time() - self._start_time
            msg = Text("  THINK ", style="none")
            msg.append("Thinking", style="bold italic #b0a0ff")
            msg.append(f" [{elapsed:.1f}s] ", style="#6b7280")
            msg.append(f"... {display}", style="italic #94a3b8")
            self._static_reasoning.update(msg, layout=False)

    def append_reasoning(self, token: str) -> None:
        self._has_reasoning = True
        self._reasoning += token
        if self._static_loader:
            self._static_loader.update("", layout=False)

        now = time.time()
        if now - self._last_stream_update >= 0.04:
            self._last_stream_update = now
            self._flush_reasoning_content()

    def append(self, token: str) -> None:
        self._has_tokens = True
        self._buffer += token
        if self._static_loader:
            self._static_loader.update("", layout=False)

        now = time.time()
        if now - self._last_stream_update >= 0.04:
            self._last_stream_update = now
            self._flush_stream_content()

    def finalize(self, full_content: str) -> None:
        if self._timer:
            self._timer.stop()
            self._timer = None

        self._buffer = full_content
        if self._static_loader:
            self._static_loader.update("")

        elapsed = time.time() - self._start_time
        if self._static_reasoning:
            if self._reasoning:
                msg = Text("  THINK ", style="none")
                msg.append(f"Thought process complete ({elapsed:.1f}s)", style="italic #64748b")
                self._static_reasoning.update(msg)
            else:
                self._static_reasoning.update("")

        if self._static_content:
            from rich.markdown import Markdown
            try:
                self._static_content.update(Markdown(full_content.strip(), code_theme="monokai"))
            except Exception:
                self._static_content.update(Text(f"  {full_content}", style=C_TEXT))

    def on_unmount(self) -> None:
        if self._timer:
            self._timer.stop()
            self._timer = None


TOOL_EMOJIS = {
    "read": "📖",
    "read_file": "📖",
    "grep": "🔎",
    "search_files": "🔎",
    "glob": "🗂️",
    "list_files": "🗂️",
    "webfetch": "🌐",
    "websearch": "🌐",
    "search_web": "🌐",
    "web_extract": "🌐",
    "lsp": "🧭",
    "code_intelligence": "🧭",
    "skill": "🧠",
    "list_skills": "🧠",
    "git_status": "🌿",
    "git_diff": "🌿",
    "git_log": "🌿",
    "write": "📝",
    "write_file": "📝",
    "edit": "📝",
    "edit_file": "📝",
    "apply_patch": "📝",
    "shell": "⚡",
    "run_shell": "⚡",
    "bash": "⚡",
    "todowrite": "📋",
    "todo": "📋",
    "remember": "💾",
    "memory": "💾",
}


def _extract_summary(tool_name: str, output: str) -> str:
    """Extract a concise one-line summary for read/grep/glob without showing raw code."""
    import re
    if tool_name in ("read", "read_file"):
        lines = [l for l in output.splitlines() if l.strip()]
        if not lines:
            return "tidak ada baris"
        # Check if line numbers are present
        count = sum(1 for l in lines if re.match(r"^\s*\d+:", l))
        if count:
            return f"{count} baris dibaca"
        return f"{len(lines)} baris dibaca"
    if tool_name in ("grep", "search_files"):
        m = re.search(r"Found\s+(\d+)\s+match", output)
        if m:
            c = m.group(1)
            # count distinct files
            files = set(re.findall(r"^\s*([^\s:]+):", output, re.MULTILINE))
            if files:
                return f"{c} cocok di {len(files)} file"
            return f"{c} cocok"
        if "No matches found" in output:
            return "tidak ada cocok"
        return "pencarian selesai"
    if tool_name in ("glob", "list_files"):
        lines = [l for l in output.splitlines() if l.strip() and not l.startswith("Directory:")]
        if not lines:
            return "tidak ada file"
        return f"{len(lines)} item"
    return "selesai"


def _render_diff_text(diff_str: str, max_lines: int = 120) -> Text:
    """Fast, zero-pygments line-colored diff rendering with Rich Text.
    Prevents TUI render stalls caused by heavy Syntax / Pygments lexers.
    """
    t = Text()
    lines = diff_str.splitlines()
    total = len(lines)
    truncated = False
    if total > max_lines:
        lines = lines[:max_lines]
        truncated = True

    for i, line in enumerate(lines):
        if i > 0:
            t.append("\n")
        if line.startswith("+++ ") or line.startswith("--- "):
            t.append(f"    {line}", style="bold #9999bb")
        elif line.startswith("+"):
            t.append(f"    {line}", style="#4ade80")  # bright green
        elif line.startswith("-"):
            t.append(f"    {line}", style="#f87171")  # soft red
        elif line.startswith("@@"):
            t.append(f"    {line}", style="bold #c084fc")  # purple context
        elif line.startswith("📝 "):
            t.append(f"  {line}", style="bold #38bdf8")  # cyan file header
        else:
            t.append(f"    {line}", style="#94a3b8")

    if truncated:
        t.append(f"\n    ... ({total - max_lines} baris dipotong)", style="dim #64748b")

    return t


class FastCodeBlock(CodeBlock):
    """Fast zero-pygments diff and cached code block renderer for Rich Markdown.
    Prevents Pygments from re-tokenizing code blocks on every screen render pass.
    """
    def __init__(self, lexer_name: str, theme: str) -> None:
        super().__init__(lexer_name, theme)
        self._cached_render = None

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        if self._cached_render is None:
            code = str(self.text).rstrip()
            if self.lexer_name.lower() in ("diff", "udiff", "patch") or (code.startswith("--- ") or code.startswith("+++ ") or code.startswith("@@")):
                self._cached_render = _render_diff_text(code)
            else:
                try:
                    self._cached_render = Syntax(code, self.lexer_name, theme=self.theme, word_wrap=True, padding=1)
                except Exception:
                    self._cached_render = Text(f"    {code}", style="#c8d3f5")
        yield self._cached_render


Markdown.elements["fence"] = FastCodeBlock
Markdown.elements["code_block"] = FastCodeBlock


class ToolCallCard(Widget):
    """OpenCode-style tool call card with live star spinner and dynamic status update."""

    DEFAULT_CSS = """
    ToolCallCard {
        margin: 0 0 1 0;
        padding: 0 1;
        background: #111118;
        border-left: solid #FFD700;
        height: auto;
    }
    """

    SPIN_FRAMES = [
        "[ EXECUTING ]",
        "[ EXECUTING ]",
        "[ EXECUTING ]",
        "[ EXECUTING ]",
    ]

    def __init__(self, tool_name: str, desc: str, output: str = "", status: str = "running", diff: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._tool_name = tool_name
        self._desc = desc
        self._output = output
        self._status = status  # running | done | rejected | error
        self._diff = diff
        self._cached_diff_render: Text | None = _render_diff_text(diff) if diff else None
        self._frame = 0
        self._timer = None
        self._static_header: Static | None = None
        self._static_output: Static | None = None

    def compose(self) -> ComposeResult:
        self._static_header = Static("")
        yield self._static_header

        self._static_output = Static("")
        yield self._static_output

    def on_mount(self) -> None:
        self._render_card()
        if self._status == "running":
            self._timer = self.set_interval(0.12, self._tick_tool)

    def _tick_tool(self) -> None:
        if self._status != "running":
            if self._timer:
                self._timer.stop()
                self._timer = None
            return

        self._frame += 1
        badge_text = self.SPIN_FRAMES[self._frame % len(self.SPIN_FRAMES)]
        color = STAR_COLORS[self._frame % len(STAR_COLORS)]

        header = Text(f"  ◆ {self._tool_name} ", style="bold #b0a0ff")
        header.append(badge_text, style=f"bold {color}")
        if self._desc:
            header.append(f"  {self._desc}", style="#9999bb")

        if self._static_header:
            self._static_header.update(header)

    def update_result(self, output: str, status: str = "done", diff: str = "") -> None:
        """Dynamically updates running card to completed status."""
        if self._timer:
            self._timer.stop()
            self._timer = None

        if self._status == status and self._output == output and (not diff or self._diff == diff):
            return

        self._output = output
        self._status = status
        if diff:
            self._diff = diff
            self._cached_diff_render = _render_diff_text(diff)
        self._render_card()

    def _render_card(self) -> None:
        if self._status == "running" and self.is_mounted and self._timer is None:
            self._timer = self.set_interval(0.12, self._tick_tool)
        elif self._status != "running" and self._timer:
            self._timer.stop()
            self._timer = None

        emoji = TOOL_EMOJIS.get(self._tool_name, "◆")
        is_read_tool = self._tool_name in ("read", "read_file", "grep", "search_files", "glob", "list_files")

        badge_style = {
            "preparing": "bold #a855f7",
            "running": "bold #ffaa33",
            "done": "bold #22c55e",
            "rejected": "bold #ffaa88",
            "error": "bold #ff5555",
        }.get(self._status, "bold #9b88ff")

        badge_text = {
            "preparing": "[ MENYIAPKAN ]",
            "running": "[ RUNNING ]",
            "done": "[ DONE ]",
            "rejected": "[ REJECTED ]",
            "error": "[ ERROR ]",
        }.get(self._status, f"[{self._status.upper()}]")

        header = Text(f"  {emoji} {self._tool_name} ", style="bold #b0a0ff")
        header.append(badge_text, style=badge_style)
        if self._desc:
            header.append(f"  {self._desc}", style="#9999bb")

        # In concise read/search mode: append summary directly on header if done
        if is_read_tool and self._status == "done":
            summary = _extract_summary(self._tool_name, self._output)
            header.append(f"  ✓ {summary}", style="bold #22c55e")

        if self._static_header:
            self._static_header.update(header)

        if self._static_output:
            if is_read_tool:
                # Do NOT display raw output for read/search tools!
                # Only show single line reason if error or rejected
                if self._status in ("error", "rejected") and self._output:
                    err_line = self._output.strip().splitlines()[0][:100]
                    self._static_output.update(Text(f"    ✗ {err_line}", style="#ff8888"))
                else:
                    self._static_output.update("")
            elif self._diff:
                # File mutation tools with lightweight zero-pygments colored diff
                if self._cached_diff_render is None:
                    self._cached_diff_render = _render_diff_text(self._diff)
                self._static_output.update(self._cached_diff_render)
            elif self._output:
                out_preview = self._output[:1200]
                if len(self._output) > 1200:
                    out_preview += f"\n... ({len(self._output) - 1200:,} more chars)"
                if self._tool_name in ("edit", "edit_file", "apply_patch") or ("@@" in out_preview and ("\n+" in out_preview or "\n-" in out_preview)):
                    if self._cached_diff_render is None:
                        self._cached_diff_render = _render_diff_text(out_preview)
                    self._static_output.update(self._cached_diff_render)
                else:
                    self._static_output.update(Text(f"    {out_preview}", style="#c8f0c8"))
            else:
                self._static_output.update("")

    def on_unmount(self) -> None:
        if self._timer:
            self._timer.stop()
            self._timer = None
