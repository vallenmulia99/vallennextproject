"""VALLEN CLI — Main Textual TUI application."""

from __future__ import annotations

import asyncio
import subprocess
import os
import time
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    TextArea,
    Button,
    Tree,
)
from textual.screen import Screen, ModalScreen

from ..core.config import get_config
from ..core.workspace import get_workspace
from ..core.git_info import get_git_branch_sync
from ..core.session import get_session_manager
from ..providers.registry import get_registry, ProviderStatus
from ..commands.processor import process_input, CommandResult
from ..core.agent import run_agent, AgentEvent
from .widgets.message import ChatMessage, StreamingMessage, ToolCallCard
from .widgets.model_picker import ModelPickerScreen
from .widgets.hub_modal import HubModalScreen
from .widgets.permission_modal import PermissionModal
from .widgets.question_modal import QuestionModal
from ..core.permission import get_permission_manager, PermRequest, PermReply
from ..core.health import get_health_monitor
from ..tools.agent_tools import get_todos, get_pending_question, answer_question


# ============================================================
# Splash / First-launch screen
# ============================================================

LOGO = """\
██╗   ██╗ █████╗ ██╗     ██╗     ███████╗███╗   ██╗
██║   ██║██╔══██╗██║     ██║     ██╔════╝████╗  ██║
╚██╗ ██╔╝███████║██║     ██║     █████╗  ██╔██╗ ██║
 ╚████╔╝ ██╔══██║██║     ██║     ██╔══╝  ██║╚██╗██║
  ╚██╔╝  ██║  ██║███████╗███████╗███████╗██║ ╚████║
   ╚═╝   ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═══╝"""

TAGLINE = "V A L L E N   C L I"
SUBTITLE = "AI SOFTWARE ENGINEERING AGENT"


class SplashScreen(Screen):
    """Animated branding splash shown on first launch."""

    CSS = """
    SplashScreen {
        align: center middle;
        background: #0d0d0f;
    }
    #splash-logo {
        color: #7b68ee;
        text-align: center;
        text-style: bold;
        padding: 0 2;
    }
    #splash-tagline {
        color: #9988ff;
        text-align: center;
        text-style: bold;
        padding: 1 0 0 0;
    }
    #splash-sub {
        color: #9090bb;
        text-align: center;
        padding: 0 0 0 0;
    }
    #splash-hint {
        color: #8080aa;
        text-align: center;
        padding: 2 0 0 0;
    }
    """

    BINDINGS = [
        Binding("enter", "continue", "Continue"),
        Binding("space", "continue", "Continue"),
        Binding("escape", "continue", "Skip"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(LOGO, id="splash-logo")
        yield Static(TAGLINE, id="splash-tagline")
        yield Static(SUBTITLE, id="splash-sub")
        yield Static("Press Enter to continue", id="splash-hint")

    def action_continue(self) -> None:
        self.app.push_screen(MainScreen())


# ============================================================
# Project-detected welcome screen
# ============================================================

class ProjectDetectedScreen(Screen):
    """Show detected project on launch with resume / new session choice."""

    CSS = """
    ProjectDetectedScreen {
        align: center middle;
        background: #0d0d0f;
    }
    #pd-label {
        color: #9090bb;
        text-style: bold;
        text-align: center;
    }
    #pd-name {
        color: #7b68ee;
        text-style: bold;
        text-align: center;
        padding: 1 0 0 0;
    }
    #pd-path {
        color: #9b88ff;
        text-align: center;
        padding: 0 0 1 0;
    }
    #pd-sessions-title {
        color: #7070a0;
        text-align: center;
        text-style: bold;
        padding: 1 0 0 0;
    }
    #pd-list {
        height: auto;
        border: none;
        background: transparent;
    }
    """

    BINDINGS = [
        Binding("escape", "new_session", "New session"),
        Binding("n", "new_session", "New session"),
    ]

    def __init__(self, project: dict, sessions: list[dict]) -> None:
        super().__init__()
        self._project = project
        self._sessions = sessions

    def compose(self) -> ComposeResult:
        yield Static("PROJECT DETECTED", id="pd-label")
        yield Static(self._project.get("name", ""), id="pd-name")
        yield Static(self._project.get("path", ""), id="pd-path")
        yield Static("Recent sessions", id="pd-sessions-title")
        items = []
        if self._sessions:
            items.append(ListItem(Label("› Continue last session")))
        items.append(ListItem(Label("  New session")))
        yield ListView(*items, id="pd-list")

    def on_mount(self) -> None:
        self.query_one("#pd-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx == 0 and self._sessions:
            # Resume last session
            ws = get_workspace()
            sess = get_session_manager()
            last = self._sessions[0]
            sess.resume(last["id"])
            self.app.push_screen(MainScreen())
        else:
            self.action_new_session()

    def action_new_session(self) -> None:
        sess = get_session_manager()
        sess.start_new()
        self.app.push_screen(MainScreen())


# ============================================================
# Sidebar
# ============================================================

class SidebarWidget(Widget):
    """Left sidebar — interactive collapsible project file tree and sessions."""

    DEFAULT_CSS = """
    SidebarWidget {
        width: 26;
        background: #0c0c12;
        border-right: solid #1e1e2e;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            title_text = Text("PROJECT TREE", style="bold #67e8f9")
            yield Static(title_text, classes="sidebar-section-title")
            yield Tree("workspace", id="sb-file-tree")
            tasks_text = Text("TASKS & SESSIONS", style="bold #a78bfa")
            yield Static(tasks_text, classes="sidebar-section-title")
            yield Static("", id="sb-tasks-sessions", classes="sidebar-tasks-box")

    def on_mount(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        ws = get_workspace()
        sess = get_session_manager()
        project_path = ws.active_project_path

        # 1. Populate tree (empty unless /cd has been called)
        try:
            tree = self.query_one("#sb-file-tree", Tree)
            tree.root.remove_children()

            if not project_path:
                tree.root.set_label("(No project open)")
                tree.root.data = {"path": "", "is_dir": True}
                tree.root.add_leaf("Type /cd <path> to open a project", data={"path": "", "is_dir": False})
                tree.root.expand()
            else:
                root_path = Path(project_path)
                tree.root.set_label(f"{root_path.name or 'project'}")
                tree.root.data = {"path": "", "is_dir": True}

                IGNORED = {
                    ".git", "__pycache__", "node_modules", ".venv", "venv",
                    ".next", ".pytest_cache", ".mypy_cache", "dist", "build",
                }

                def _add_nodes(parent, directory: Path, depth: int):
                    if depth > 2:
                        return
                    try:
                        entries = sorted(directory.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
                    except Exception:
                        return
                    for entry in entries:
                        if entry.name in IGNORED or entry.name.endswith(".egg-info") or (entry.name.startswith(".") and entry.name not in (".vallen", ".opencode")):
                            continue
                        try:
                            rel = str(entry.relative_to(root_path))
                        except ValueError:
                            rel = entry.name
                        if entry.is_dir():
                            node = parent.add(f"{entry.name}", data={"path": rel, "is_dir": True})
                            if depth < 2:
                                node.expand()
                            _add_nodes(node, entry, depth + 1)
                        else:
                            parent.add_leaf(f"{entry.name}", data={"path": rel, "is_dir": False})

                _add_nodes(tree.root, root_path, 1)
                tree.root.expand()
        except NoMatches:
            pass

        # 2. Show recent sessions & tasks
        try:
            if not project_path:
                self.query_one("#sb-tasks-sessions").update("  Type /cd <path>\n  to open a project")
            else:
                grouped = sess.list_grouped()
                lines = []
                for group, sessions in grouped.items():
                    if not sessions:
                        continue
                    lines.append(f"  {group}")
                    for s in sessions[:2]:
                        marker = "›" if s.get("id") == sess.session_id else " "
                        title = _truncate(s.get("title", "Session"), 14)
                        lines.append(f"  {marker} {title}")

                todos = get_todos()
                if todos:
                    res_text = Text()
                    if lines:
                        res_text.append("\n".join(lines) + "\n\n")
                    res_text.append("  SUBTASKS\n", style="bold #FFD700")
                    for t in todos[-6:]:
                        st = t.get("status", "pending")
                        content = _truncate(t.get("content", ""), 18)
                        if st == "completed":
                            res_text.append(f"  OK: {content}\n", style="#22c55e")
                        elif st == "in_progress":
                            res_text.append(f"  {content}\n", style="bold #f59e0b")
                        else:
                            res_text.append(f"  ○ {content}\n", style="#94a3b8")
                    self.query_one("#sb-tasks-sessions").update(res_text)
                else:
                    self.query_one("#sb-tasks-sessions").update("\n".join(lines) or "  No recent sessions")
        except NoMatches:
            pass

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.node.data and not event.node.data.get("is_dir"):
            rel_path = event.node.data.get("path")
            if rel_path:
                try:
                    chat_input = self.app.screen.query_one(ChatInputArea)
                    main_input = chat_input.query_one("#main-input", ChatTextArea)
                    main_input.insert(f"@{rel_path} ")
                    main_input.focus()
                except NoMatches:
                    pass


# ============================================================
# Context panel
# ============================================================

class ContextPanel(Widget):
    """Right panel — model, provider, status."""

    DEFAULT_CSS = """
    ContextPanel {
        width: 20;
        background: #0d0d0f;
        border-left: solid #1e1e2e;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    _status: ProviderStatus = ProviderStatus.UNKNOWN

    def compose(self) -> ComposeResult:
        yield Static(Text("MODEL", style="bold #a0a0cc"), classes="context-label")
        yield Static("", id="ctx-model", classes="context-value-active")
        yield Static(Text("PROVIDER", style="bold #a0a0cc"), classes="context-label")
        yield Static("", id="ctx-provider", classes="context-value")
        yield Static("", id="ctx-status", classes="context-value")
        yield Static(Text("WORKSPACE", style="bold #a0a0cc"), classes="context-label")
        yield Static("", id="ctx-project", classes="context-value")
        yield Static(Text("SESSION", style="bold #a0a0cc"), classes="context-label")
        yield Static("", id="ctx-session", classes="context-value")
        yield Static(Text("MESSAGES", style="bold #a0a0cc"), classes="context-label")
        yield Static("", id="ctx-msgs", classes="context-value")

    def refresh_content(self, status: ProviderStatus | None = None) -> None:
        if status is not None:
            self._status = status
        cfg = get_config()
        ws = get_workspace()
        sess = get_session_manager()
        registry = get_registry()
        disp = registry.display_name(cfg.active_provider)
        try:
            self.query_one("#ctx-model").update(_truncate(cfg.active_model, 16))
            self.query_one("#ctx-provider").update(disp)

            if self._status == ProviderStatus.CONNECTED:
                self.query_one("#ctx-status").update(
                    Text("Connected", style="#44aa66")
                )
            elif self._status == ProviderStatus.OFFLINE:
                self.query_one("#ctx-status").update(
                    Text("Offline", style="#aa4444")
                )
            else:
                self.query_one("#ctx-status").update(
                    Text("Unknown", style="#a0a0cc")
                )

            self.query_one("#ctx-project").update(
                _truncate(ws.active_project_name or "—", 16)
            )
            self.query_one("#ctx-session").update(
                _truncate(sess.title or "—", 16)
            )
            self.query_one("#ctx-msgs").update(str(sess.message_count))
        except NoMatches:
            pass


# ============================================================
# Header bar
# ============================================================

class HeaderBar(Widget):
    """Compact single-line header."""

    DEFAULT_CSS = """
    HeaderBar {
        height: 1;
        background: #0d0d0f;
        layout: horizontal;
        padding: 0 2;
        border-bottom: solid #1e1e2e;
    }
    """

    def compose(self) -> ComposeResult:
        brand = Text("VALLEN", style="bold #FF6B00")
        brand.append(" NEXSUS", style="bold #DC143C")
        yield Static(brand, id="hb-brand")
        yield Static("", id="hb-project")
        yield Static("", id="hb-model")
        yield Static("", id="hb-provider")
        hub_text = Text(" [Ctrl+M Hub] ", style="bold #FF6B00")
        yield Static(hub_text, id="hb-hub")

    def refresh_content(self, status: ProviderStatus = ProviderStatus.UNKNOWN) -> None:
        cfg = get_config()
        ws = get_workspace()
        registry = get_registry()
        disp = registry.display_name(cfg.active_provider)
        dot = {
            ProviderStatus.CONNECTED: Text("●", style="#22c55e"),
            ProviderStatus.OFFLINE: Text("●", style="#ef4444"),
        }.get(status, Text("●", style="#a0a0cc"))
        try:
            if ws.active_project_path:
                project_path = ws.active_project_path
                branch = get_git_branch_sync(project_path)
                branch_tag = f" ({branch})" if branch else ""
                proj_label = f"  {ws.active_project_name or Path(project_path).name}{branch_tag}"
                proj_style = "#e2e8f0"
            else:
                proj_label = "  (no project - use /cd)"
                proj_style = "#94a3b8"
            self.query_one("#hb-project").update(
                Text(proj_label, style=proj_style)
            )
            model_text = Text(f"  {_truncate(cfg.active_model, 26)}", style="bold #DC143C")
            self.query_one("#hb-model").update(model_text)

            prov_text = Text(f" ")
            prov_text.append_text(dot)
            prov_text.append(f" {disp}", style="#cbd5e1")
            self.query_one("#hb-provider").update(prov_text)
        except NoMatches:
            pass


# ============================================================
# Footer bar
# ============================================================

class FooterBar(Widget):
    """Minimal keyboard-hint footer."""

    DEFAULT_CSS = """
    FooterBar {
        height: 1;
        background: #0b0f14;
        layout: horizontal;
        padding: 0 2;
        border-top: solid #263241;
    }
    """

    _status_text: str = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="fb-controls"):
            yield Static("", id="fb-hints")
            yield Static("", id="fb-status")

    def on_mount(self) -> None:
        hints = (
            "[bold #a78bfa]Ctrl+M[/] [#67e8f9]Hub[/]   "
            "[#8b9bad]Ctrl+P[/] [#67e8f9]Model[/]   "
            "[#8b9bad]Ctrl+B[/] [#67e8f9]Sidebar[/]   "
            "[#8b9bad]Ctrl+H[/] [#67e8f9]Halt[/]   "
            "[#8b9bad]Ctrl+N[/] [#67e8f9]New[/]   "
            "[#8b9bad]Ctrl+D[/] [#67e8f9]Quit[/]"
        )
        try:
            self.query_one("#fb-hints").update(hints)
        except NoMatches:
            pass

    def set_status(self, text: str) -> None:
        self._status_text = text
        try:
            self.query_one("#fb-status").update(Text(text, style="#a78bfa", justify="right"))
        except NoMatches:
            pass

    def set_tokens(self, display: str) -> None:
        try:
            self.query_one("#fb-hints").update(
                f"[#8b9bad]Ctrl+P[/] [#67e8f9]model[/]   [#8b9bad]Ctrl+N[/] [#67e8f9]new[/]   "
                f"[#8b9bad]Ctrl+H[/] [#67e8f9]history[/]   [#263241]tokens: {display}[/]"
            )
        except NoMatches:
            pass


# ============================================================
# Chat input widget
# ============================================================

# ============================================================
# Custom TextArea that intercepts Enter for submission
# ============================================================

def get_system_clipboard() -> str:
    """Read system clipboard using xclip / wl-paste / xsel."""
    for cmd in [
        ["xclip", "-o", "-selection", "clipboard"],
        ["wl-paste"],
        ["xsel", "--clipboard", "--output"],
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            continue
    return ""


def set_system_clipboard(content: str) -> None:
    """Write text to system clipboard using xclip / wl-copy / xsel."""
    for cmd in [
        ["xclip", "-selection", "clipboard"],
        ["wl-copy"],
        ["xsel", "--clipboard", "--input"],
    ]:
        try:
            r = subprocess.run(cmd, input=content, text=True, timeout=1)
            if r.returncode == 0:
                break
        except Exception:
            continue


AVAILABLE_SLASH_COMMANDS = [
    "/help", "/models", "/autopilot", "/yolo", "/plan", "/build", "/profile",
    "/diff", "/clear", "/tree", "/compact", "/revert", "/snapshot",
    "/tokens", "/todos", "/commands", "/skills", "/mcp", "/new",
    "/status", "/projects", "/sessions", "/history", "/export", "/fork", "/cd", "/debug"
]


class ChatTextArea(TextArea):
    """
    TextArea subclass:
      Enter        → post Submitted message to parent & append to history
      Up / Down    → navigate command history
      Tab          → autocomplete slash commands
      Shift+Enter  → insert newline (multiline)
      Ctrl+V       → paste from OS system clipboard
      Ctrl+C       → copy to OS system clipboard
    """

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    _history: list[str] = []
    _history_idx: int = -1
    _saved_draft: str = ""

    def action_paste(self) -> None:
        """Paste directly from system clipboard or local clipboard."""
        clip = get_system_clipboard() or self.app.clipboard
        if clip:
            self.insert(clip)

    def action_copy(self) -> None:
        """Copy selected text or entire input to system clipboard."""
        selected = self.selected_text or self.text
        if selected:
            set_system_clipboard(selected)
            self.app.copy_to_clipboard(selected)

    async def _on_key(self, event) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            text = self.text.strip()
            if text:
                if not self._history or self._history[-1] != text:
                    self._history.append(text)
                self._history_idx = -1
                self._saved_draft = ""
                self.post_message(self.Submitted(text))
        elif event.key == "up":
            if self.cursor_at_first_line and self._history:
                event.prevent_default()
                event.stop()
                if self._history_idx == -1:
                    self._saved_draft = self.text
                    self._history_idx = len(self._history) - 1
                elif self._history_idx > 0:
                    self._history_idx -= 1
                self.load_text(self._history[self._history_idx])
                self.move_cursor((0, len(self.text)))
        elif event.key == "down":
            if self.cursor_at_last_line and self._history_idx != -1:
                event.prevent_default()
                event.stop()
                if self._history_idx < len(self._history) - 1:
                    self._history_idx += 1
                    self.load_text(self._history[self._history_idx])
                else:
                    self._history_idx = -1
                    self.load_text(self._saved_draft)
                self.move_cursor((0, len(self.text)))
        elif event.key == "tab":
            curr = self.text.strip()
            if curr.startswith("/") and "\n" not in self.text:
                matches = [c for c in AVAILABLE_SLASH_COMMANDS if c.startswith(curr.lower())]
                if matches:
                    event.prevent_default()
                    event.stop()
                    if curr in matches:
                        next_idx = (matches.index(curr) + 1) % len(matches)
                        self.load_text(matches[next_idx] + " ")
                    else:
                        self.load_text(matches[0] + " ")
                    self.move_cursor((0, len(self.text)))
                    return
            await super()._on_key(event)
        elif event.key == "shift+enter":
            event.prevent_default()
            event.stop()
            self.insert("\n")
        elif event.key in ("ctrl+v", "ctrl+shift+v"):
            event.prevent_default()
            event.stop()
            self.action_paste()
        elif event.key in ("ctrl+c", "ctrl+shift+c"):
            event.prevent_default()
            event.stop()
            self.action_copy()
        elif event.key in ("ctrl+m", "ctrl+k"):
            event.prevent_default()
            event.stop()
            if hasattr(self.app.screen, "action_open_hub"):
                self.app.screen.action_open_hub()
        elif event.key == "ctrl+h":
            event.prevent_default()
            event.stop()
            if hasattr(self.app.screen, "action_cancel_generation"):
                self.app.screen.action_cancel_generation()
        elif event.key == "ctrl+b":
            event.prevent_default()
            event.stop()
            if hasattr(self.app.screen, "action_toggle_sidebar"):
                self.app.screen.action_toggle_sidebar()
        else:
            await super()._on_key(event)


# ============================================================
# Chat input widget
# ============================================================

class ChatInputArea(Widget):
    """Transparent prompt box with a subtle animated water surface."""

    TERMINAL_LABEL = "VALLEN NEXT // TERMINAL"

    WATER_FRAMES = (
        "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n ~  ~  ~  ~  ~  ~  ~  ~  ~  ~  ~  ~  ~  ~\n    .     .     .     .     .     .     .     .\n~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~",
        " ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n  ~  ~  ~  ~  ~  ~  ~  ~  ~  ~  ~  ~  ~\n .     .     .     .     .     .     .     .  \
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~",
        "  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n   ~  ~  ~  ~  ~  ~  ~  ~  ~  ~  ~  ~  ~\n     .     .     .     .     .     .     .     .\n~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~",
    )

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def compose(self) -> ComposeResult:
        with Horizontal(id="input-action-bar"):
            yield Button("Model ▾", id="chip-model")
            yield Button("Build", id="chip-mode", classes="chip-mode-build")
            yield Button("Tree", id="chip-tree")
            yield Button("Hub", id="chip-hub")
        yield Static("", id="input-prompt-label")
        yield Static("", id="input-terminal-label")
        yield ChatTextArea(id="main-input", language=None)
        yield Static(self.WATER_FRAMES[0], id="input-water")

    def _start_water_animation(self) -> None:
        self._water_frame = 0
        self._label_frame = 0
        self.set_interval(0.5, self._animate_water)
        self.set_interval(0.09, self._animate_terminal_label)

    def _animate_terminal_label(self) -> None:
        self._label_frame = (self._label_frame + 1) % (len(self.TERMINAL_LABEL) + 18)
        visible = min(self._label_frame, len(self.TERMINAL_LABEL))
        suffix = "_" if self._label_frame % 2 == 0 else " "
        try:
            self.query_one("#input-terminal-label", Static).update(
                f"  {self.TERMINAL_LABEL[:visible]}{suffix}"
            )
        except NoMatches:
            pass

    def _animate_water(self) -> None:
        self._water_frame = (self._water_frame + 1) % len(self.WATER_FRAMES)
        try:
            self.query_one("#input-water", Static).update(self.WATER_FRAMES[self._water_frame])
        except NoMatches:
            pass

    def on_click(self, event) -> None:
        self.focus_input()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        try:
            lbl = self.query_one("#input-prompt-label", Static)
            text = event.text_area.text.strip()
            if text.startswith("/"):
                matches = [c for c in AVAILABLE_SLASH_COMMANDS if c.startswith(text.lower())]
                if matches:
                    lbl.update("Tab: " + "  ".join(matches[:7]))
                else:
                    lbl.update("Unknown command (Type /help)")
            else:
                lbl.update("")
        except NoMatches:
            pass

    def on_mount(self) -> None:
        self._start_water_animation()
        self.refresh_chips()
        self.focus_input()

    def refresh_chips(self) -> None:
        cfg = get_config()
        sess = get_session_manager()
        try:
            model_btn = self.query_one("#chip-model", Button)
            active_m = cfg.active_model.split("/")[-1] if cfg.active_model else "model"
            short_model = _truncate(active_m, 18)
            model_btn.label = f"{short_model} ▾"

            mode_btn = self.query_one("#chip-mode", Button)
            cur_mode = getattr(sess, "mode", "build")
            if cur_mode == "plan":
                mode_btn.label = "Plan"
                mode_btn.remove_class("chip-mode-build")
                mode_btn.add_class("chip-mode-plan")
            else:
                mode_btn.label = "Build"
                mode_btn.remove_class("chip-mode-plan")
                mode_btn.add_class("chip-mode-build")
        except NoMatches:
            pass

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "chip-model":
            if hasattr(self.app.screen, "action_model_picker"):
                await self.app.screen.action_model_picker()
        elif bid == "chip-mode":
            sess = get_session_manager()
            cur_mode = getattr(sess, "mode", "build")
            sess.mode = "plan" if cur_mode == "build" else "build"
            self.refresh_chips()
            if hasattr(self.app.screen, "_post_system"):
                self.app.screen._post_system(f"OK: Switched to {sess.mode.upper()} mode.")
        elif bid == "chip-tree":
            if hasattr(self.app.screen, "action_toggle_sidebar"):
                self.app.screen.action_toggle_sidebar()
        elif bid == "chip-hub":
            if hasattr(self.app.screen, "action_open_hub"):
                self.app.screen.action_open_hub()

    def on_chat_text_area_submitted(self, event: ChatTextArea.Submitted) -> None:
        """Clear input immediately, then bubble up as ChatInputArea.Submitted."""
        event.stop()
        text = event.text.strip()
        if not text:
            self.focus_input()
            return
        self.clear()
        self.post_message(self.Submitted(text))

    def get_text(self) -> str:
        return self.query_one("#main-input", ChatTextArea).text

    def clear(self) -> None:
        self.query_one("#main-input", ChatTextArea).clear()

    def focus_input(self) -> None:
        self.query_one("#main-input", ChatTextArea).focus()


# ============================================================
# Main application screen
# ============================================================

class TaskStrip(Widget):
    """Compact live activity strip above chat."""

    FRAMES = ("|", "/", "-", "\\")

    DEFAULT_CSS = """
    TaskStrip {
        height: 1;
        display: none;
        padding: 0 2;
        color: #67e8f9;
        background: #0d202b;
        border-bottom: solid #17465a;
    }

    TaskStrip.active {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="task-strip-text")

    def on_mount(self) -> None:
        self._frame = 0
        self._started = 0.0
        self._timer = self.set_interval(0.25, self._tick)

    def start(self, label: str = "Working") -> None:
        self._started = time.monotonic()
        self.add_class("active")
        self._update(label)

    def update_label(self, label: str) -> None:
        if self.has_class("active"):
            self._update(label)

    def stop(self) -> None:
        self.remove_class("active")

    def _tick(self) -> None:
        if self.has_class("active"):
            self._frame = (self._frame + 1) % len(self.FRAMES)
            self._update("Working")

    def _update(self, label: str) -> None:
        elapsed = time.monotonic() - self._started
        try:
            self.query_one("#task-strip-text", Static).update(
                f"{self.FRAMES[self._frame]}  {label}  [{elapsed:.1f}s]"
            )
        except NoMatches:
            pass

class MainScreen(Screen):
    """The primary VALLEN TUI screen."""

    CSS_PATH = "vallen.tcss"

    BINDINGS = [
        Binding("ctrl+m", "open_hub", "Control Hub", show=False),
        Binding("ctrl+k", "open_hub", "Commands", show=False),
        Binding("ctrl+b", "toggle_sidebar", "Toggle Sidebar", show=False),
        Binding("ctrl+p", "model_picker", "Model picker", show=False),
        Binding("ctrl+r", "refresh_cli", "Refresh CLI", show=False),
        Binding("ctrl+n", "new_session", "New session", show=False),
        Binding("ctrl+s", "history", "History", show=False),
        Binding("ctrl+h", "cancel_generation", "Halt / Cancel", show=False),
        Binding("ctrl+d", "quit", "Quit", show=False),
    ]

    _generating: bool = False
    _autopilot: bool = False
    _cancel_event: asyncio.Event | None = None

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header-bar")
        yield TaskStrip(id="task-strip")
        with Horizontal(id="body"):
            yield SidebarWidget(id="sidebar", classes="-hidden")
            with Vertical(id="chat-column"):
                yield ScrollableContainer(id="chat-panel")
                yield ChatInputArea(id="input-area")
        yield FooterBar(id="footer-bar")

    def on_mount(self) -> None:
        self._refresh_ui()
        self.check_provider_status()
        # Register permission callback
        self._register_permission_callback()
        # Start health monitor
        monitor = get_health_monitor()
        monitor.on_status_change(self._on_health_status_change)
        monitor.start()
        # Royal Welcome banner
        ws = get_workspace()
        sess = get_session_manager()
        cfg = get_config()
        project_path = ws.active_project_path or os.getcwd()
        branch = get_git_branch_sync(project_path)
        branch_str = f" ({branch})" if branch else ""

        if sess.message_count == 0:
            _banner_file = Path(__file__).parent / "banner.txt"
            try:
                _ascii_banner = _banner_file.read_text(encoding="utf-8").rstrip("\n")
            except Exception:
                _ascii_banner = "VALLEN NEXUS"

            welcome_text = (
                f"{_ascii_banner}\n"
                f"Type /help for commands"
            )
            self._post_system(welcome_text)
        self.query_one(ChatInputArea).focus_input()

    def _register_permission_callback(self) -> None:
        """Register async TUI callbacks for permission + question tools."""
        import asyncio
        perm = get_permission_manager()

        async def ask_permission(request: PermRequest) -> PermReply:
            future: asyncio.Future[PermReply] = asyncio.get_event_loop().create_future()

            def on_dismiss(result: PermReply | None) -> None:
                reply = result if result is not None else PermReply.REJECT
                if not future.done():
                    future.set_result(reply)

            self.app.push_screen(PermissionModal(request), on_dismiss)
            return await future

        perm.set_callback(ask_permission)

        # Register question tool callback
        from ..tools.agent_tools import QuestionTool
        import vallen_cli.tools.agent_tools as _at

        async def ask_question_callback(question: str, options: list[str]) -> str:
            future: asyncio.Future[str] = asyncio.get_event_loop().create_future()

            def on_dismiss(result: str | None) -> None:
                answer = result if result else "(no answer)"
                if not future.done():
                    future.set_result(answer)

            self.app.push_screen(QuestionModal(question, options), on_dismiss)
            return await future

        _at._question_ask_callback = ask_question_callback

    # ----------------------------------------------------------------
    # UI refresh helpers
    # ----------------------------------------------------------------

    def _refresh_ui(self, status: ProviderStatus | None = None) -> None:
        try:
            hb = self.query_one(HeaderBar)
            hb.refresh_content(status or ProviderStatus.UNKNOWN)
        except NoMatches:
            pass
        try:
            sb = self.query_one(SidebarWidget)
            sb.refresh_content()
        except NoMatches:
            pass
        try:
            cp = self.query_one(ContextPanel)
            cp.refresh_content(status)
        except NoMatches:
            pass

    @work(thread=False)
    async def check_provider_status(self) -> None:
        registry = get_registry()
        status = await registry.check_active()
        self._refresh_ui(status)
        try:
            fb = self.query_one(FooterBar)
            if status == ProviderStatus.CONNECTED:
                fb.set_status("Connected")
            elif status == ProviderStatus.OFFLINE:
                fb.set_status("Provider offline")
        except NoMatches:
            pass

    # ----------------------------------------------------------------
    # Chat panel helpers
    # ----------------------------------------------------------------

    def _post_system(self, text: str) -> None:
        panel = self.query_one("#chat-panel", ScrollableContainer)
        panel.mount(ChatMessage("system_info", text))
        panel.scroll_end(animate=False)

    def _post_message(self, role: str, content: str) -> None:
        panel = self.query_one("#chat-panel", ScrollableContainer)
        panel.mount(ChatMessage(role, content))
        panel.scroll_end(animate=False)

    def _clear_chat(self) -> None:
        panel = self.query_one("#chat-panel", ScrollableContainer)
        for child in list(panel.children):
            child.remove()

    # ----------------------------------------------------------------
    # Input submission — driven by ChatInputArea.Submitted message
    # ----------------------------------------------------------------

    @on(ChatInputArea.Submitted)
    async def on_chat_input_submitted(self, message: ChatInputArea.Submitted) -> None:
        await self._submit(message.text)

    async def _submit(self, raw: str) -> None:
        if self._generating:
            return

        # Process internal commands
        result = await process_input(raw)

        if result.handled:
            # Handle side-effects
            if result.clear_chat:
                self._clear_chat()

            if result.data and isinstance(result.data, dict):
                action = result.data.get("action")
                if action == "open_hub":
                    self.action_open_hub()
                    return
                if action == "open_model_picker":
                    self.action_model_picker()
                    return
                if action == "compact":
                    self._do_compact()
                    return
                if action == "revert_all":
                    self._do_revert_all()
                    return
                if action == "revert_file":
                    self._do_revert_file(result.data.get("path", ""))
                    return
                if action == "switch_session":
                    sid = result.data.get("session_id", "")
                    if sid:
                        sess = get_session_manager()
                        sess.resume(sid)
                        self._clear_chat()
                        self._refresh_ui()
                        self._post_system(f"OK: Switched to forked session: {sid[:8]}")

                if action == "toggle_autopilot":
                    self._autopilot = bool(result.data.get("autopilot", False))
                    self._refresh_ui()
                    return

                # If project changed, refresh UI
                if "project" in result.data or "session_id" in result.data:
                    self._refresh_ui()
                    try:
                        self.query_one(SidebarWidget).refresh_content()
                    except NoMatches:
                        pass

            if result.output:
                kind = result.kind
                if kind == "error":
                    self._post_message("error", result.output)
                else:
                    self._post_message("system_info", result.output)

            # If there's a transformed prompt (e.g. @file injection), send to AI
            if result.new_prompt:
                model_override = result.data.get("model") if (result.data and isinstance(result.data, dict)) else None
                self._run_agent(result.new_prompt, model=model_override)
                return

            return

        # Not an internal command — send straight to AI agent
        self._run_agent(raw)

    @work(thread=False)
    async def _run_agent(self, user_input: str, model: str | None = None) -> None:
        self._generating = True
        self._cancel_event = asyncio.Event()
        panel = self.query_one("#chat-panel", ScrollableContainer)
        footer = self.query_one(FooterBar)
        task_strip = self.query_one(TaskStrip)
        input_area = self.query_one(ChatInputArea)
        input_area.disabled = True

        # Show user message
        self._post_message("user", user_input)

        # Create initial streaming message widget
        stream_widget: StreamingMessage | None = StreamingMessage()
        panel.mount(stream_widget)
        panel.scroll_end(animate=False)

        try:
            footer.set_status("VALLEN NEXSUS [ GENERATING... ]")
            task_strip.start("Thinking")
            full_response = ""
            cancel = self._cancel_event
            active_tool_card: ToolCallCard | None = None
            agent_task: asyncio.Task | None = None

            def on_event(event: AgentEvent) -> None:
                nonlocal full_response, active_tool_card, stream_widget
                if cancel.is_set():
                    return
                if event.kind == "token":
                    if stream_widget is None:
                        stream_widget = StreamingMessage()
                        panel.mount(stream_widget)
                    stream_widget.append(event.data)
                    panel.scroll_end(animate=False)
                elif event.kind == "reasoning":
                    if stream_widget is None:
                        stream_widget = StreamingMessage()
                        panel.mount(stream_widget)
                    stream_widget.append_reasoning(event.data)
                    panel.scroll_end(animate=False)
                elif event.kind == "token_usage":
                    try:
                        footer.set_tokens(event.data.get("display", ""))
                    except Exception:
                        pass
                elif event.kind == "compact":
                    status = event.data.get("status", "")
                    if status == "starting":
                        self._post_system("  Auto compact — summarizing session...")
                    elif status == "done":
                        self._post_system("  OK: Session compacted. Context reset with summary.")
                    elif isinstance(status, str) and status.startswith("  "):
                        self._post_system(status)
                elif event.kind == "tool_start":
                    task_strip.update_label(f"Running {event.data.get('name', 'tool')}")
                    if stream_widget is not None:
                        if not stream_widget._has_tokens and not stream_widget._has_reasoning:
                            stream_widget.remove()
                            stream_widget = None
                        else:
                            stream_widget.finalize(stream_widget._buffer)
                            stream_widget = None

                    tool_name = event.data.get("name", "")
                    desc = event.data.get("description", "")
                    active_tool_card = ToolCallCard(tool_name=tool_name, desc=desc, status="running")
                    panel.mount(active_tool_card)
                    panel.scroll_end(animate=False)
                elif event.kind == "tool_result":
                    task_strip.update_label("Updating workspace")
                    tool_name = event.data.get("name", "")
                    output = event.data.get("output", "")
                    success = event.data.get("success", True)
                    rejected = event.data.get("rejected", False)
                    status = "rejected" if rejected else ("done" if success else "error")
                    if active_tool_card is not None:
                        active_tool_card.update_result(output, status=status)
                        active_tool_card = None
                    else:
                        card = ToolCallCard(tool_name=tool_name, desc="", output=output, status=status)
                        panel.mount(card)
                    panel.scroll_end(animate=False)
                    if tool_name in ("todowrite", "todo"):
                        try:
                            self.query_one(SidebarWidget).refresh_content()
                        except NoMatches:
                            pass
                elif event.kind == "provider_retry":
                    attempt = event.data.get("attempt", "?")
                    max_attempts = event.data.get("max_attempts", "?")
                    task_strip.update_label(f"Respawning agent ({attempt}/{max_attempts})")
                    self._post_system(f"  Provider stream interrupted. Respawning agent ({attempt}/{max_attempts})...")
                elif event.kind == "error":
                    self._post_message("error", event.data)
                elif event.kind == "done":
                    full_response = event.data

            # Wrap run_agent in a Task so we can cancel it as a second safety net
            async def run_agent_wrapper():
                return await run_agent(user_input, on_event=on_event, model=model, autopilot=self._autopilot, cancel_event=cancel)

            agent_task = asyncio.create_task(run_agent_wrapper())
            self._agent_task = agent_task  # Store for cancel access
            try:
                full_response = await agent_task
            except asyncio.CancelledError:
                full_response = ""
                if on_event:
                    on_event(AgentEvent("info", "Agent task cancelled"))
            finally:
                self._agent_task = None

            if stream_widget is not None:
                if cancel.is_set():
                    stream_widget.finalize("[Cancelled]")
                else:
                    stream_widget.finalize(stream_widget._buffer or full_response)
            elif full_response and not cancel.is_set():
                self._post_message("assistant", full_response)

        except Exception as e:
            if stream_widget:
                stream_widget.finalize(f"[Error: {e}]")
            self._post_message("error", str(e))
        finally:
            footer.set_status("READY | VALLEN NEXSUS")
            self._generating = False
            self._cancel_event = None
            footer.set_status("")
            task_strip.stop()
            input_area.disabled = False
            input_area.focus_input()
            self._refresh_ui()

    # ----------------------------------------------------------------
    # Bindings / actions
    # ----------------------------------------------------------------

    def action_open_hub(self) -> None:
        self.app.push_screen(HubModalScreen())

    def action_refresh_cli(self) -> None:
        """Reload runtime state and repaint CLI without clearing the session."""
        get_registry().reload()
        self._refresh_ui()
        self.check_provider_status()
        try:
            self.query_one(SidebarWidget).refresh_content()
            self.query_one(ChatInputArea).focus_input()
        except NoMatches:
            pass
        self.refresh()
        self._post_system("CLI refreshed. Session and chat preserved.")

    def action_toggle_sidebar(self) -> None:
        try:
            sidebar = self.query_one("#sidebar", SidebarWidget)
            sidebar.toggle_class("-hidden")
        except NoMatches:
            pass

    async def action_model_picker(self) -> None:
        def on_dismiss(result: dict | None) -> None:
            if result:
                get_registry().reload()
                self._refresh_ui()
                self.check_provider_status()
                self._post_system(
                    f"OK: Model changed: {result['model']}  ({result['provider']})"
                )
        await self.app.push_screen(ModelPickerScreen(), on_dismiss)

    def action_new_session(self) -> None:
        sess = get_session_manager()
        sess.start_new()
        self._clear_chat()
        self._refresh_ui()
        self._post_system("New session started. Start chatting or use 'vall help'.")

    def action_history(self) -> None:
        self.run_worker(self._show_history())

    async def _show_history(self) -> None:
        sess = get_session_manager()
        grouped = sess.list_grouped()
        lines = ["Sessions\n"]
        for group, sessions in grouped.items():
            if not sessions:
                continue
            lines.append(f"{group}")
            for s in sessions:
                sid_short = s["id"][:8]
                title = s.get("title", "Session")
                lines.append(f"  › {title}  [{sid_short}]")
            lines.append("")
        self._post_system("\n".join(lines))

    def action_command_palette(self) -> None:
        self._post_system(
            "Command Palette\n"
            "──────────────────────────────────\n"
            "  vall new project <path>   buat workspace\n"
            "  vall projects             list project\n"
            "  vall sessions             list session\n"
            "  vall status               status saat ini\n"
            "  /models  atau  Ctrl+P     ganti model\n"
            "  Ctrl+R                     refresh CLI\n"
            "  /clear                    kosongkan chat\n"
            "  /new                      session baru\n"
            "  /tree                     file tree\n"
            "  !<cmd>                    shell command\n"
            "  @file.py                  inject file\n"
            "  /help                     bantuan lengkap\n"
            "──────────────────────────────────"
        )

    def action_cancel_generation(self) -> None:
        if self._cancel_event:
            self._cancel_event.set()
        # Also cancel the agent task if it exists (second safety net)
        if hasattr(self, '_agent_task') and self._agent_task:
            self._agent_task.cancel()

    def action_quit(self) -> None:
        # Stop health monitor on quit
        get_health_monitor().stop()
        self.app.exit()

    def _on_health_status_change(self, status: ProviderStatus) -> None:
        """Called by health monitor when provider status changes."""
        self._refresh_ui(status)
        try:
            fb = self.query_one(FooterBar)
            if status == ProviderStatus.CONNECTED:
                fb.set_status("Reconnected OK")
            elif status == ProviderStatus.OFFLINE:
                fb.set_status("Provider offline")
        except Exception:
            pass

    @work(thread=False)
    async def _do_compact(self) -> None:
        from ..core.compact import compact_session
        footer = self.query_one(FooterBar)
        footer.set_status("Compacting...")
        self._post_system("  Compacting session — summarizing conversation...")

        def on_status(msg: str) -> None:
            self._post_system(msg)

        success, summary = await compact_session(on_status=on_status)
        if success:
            self._post_system(f"  OK: Session compacted.\n\n  Summary:\n{summary[:400]}{'...' if len(summary) > 400 else ''}")
        else:
            self._post_message("error", f"Compact failed: {summary}")
        footer.set_status("")
        self._refresh_ui()

    @work(thread=False)
    async def _do_revert_all(self) -> None:
        from ..core.file_tracker import get_file_tracker
        tracker = get_file_tracker()
        if not tracker.has_changes:
            self._post_system("  No file changes to revert.")
            return
        self._post_system("  Reverting all file changes...")
        results = await tracker.revert_all()
        lines = ["  Revert results:\n"]
        for path, ok, msg in results:
            icon = "OK" if ok else "ERROR"
            lines.append(f"  {icon} {msg}")
        self._post_system("\n".join(lines))

    @work(thread=False)
    async def _do_revert_file(self, path: str) -> None:
        from ..core.file_tracker import get_file_tracker
        tracker = get_file_tracker()
        if not path:
            self._post_system("  Usage: /revert <path>")
            return
        ok, msg = await tracker.revert(path)
        icon = "OK" if ok else "ERROR"
        self._post_system(f"  {icon} {msg}")


# ============================================================
# Main application
# ============================================================

class VallenApp(App):
    """VALLEN CLI application root."""

    TITLE = "VALLEN"
    CSS_PATH = "vallen.tcss"

    def on_mount(self) -> None:
        ws = get_workspace()
        sess = get_session_manager()

        # Start with empty workspace tree as requested by user
        # (Only loads folder when user executes /cd <path>)
        ws._active_project = None
        sess.start_new()

        self.push_screen(MainScreen())


# ============================================================
# Helpers
# ============================================================

def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "..."
