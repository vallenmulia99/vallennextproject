"""VALLEN CLI — Control Hub & Help Modal Screen (Ctrl+V / Ctrl+K)."""

from __future__ import annotations

import os
from pathlib import Path
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Static, Button

from ...core.config import get_config
from ...core.workspace import get_workspace
from ...core.session import get_session_manager
from ...core.git_info import get_git_branch_sync
from ...core.custom_commands import load_custom_commands
from ...core.skills import get_skills


class HubModalScreen(ModalScreen):
    """Luxury Control Hub & Help Modal Screen."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("enter", "dismiss", "Close"),
        Binding("space", "dismiss", "Close"),
        Binding("ctrl+m", "dismiss", "Close"),
        Binding("ctrl+k", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    CSS = """
    HubModalScreen {
        align: center middle;
        background: #000000 80%;
    }

    #hub-container {
        width: 86;
        height: 85%;
        background: #0e0e14;
        border: solid #FFD700;
        padding: 1 2;
    }

    #hub-header {
        text-align: center;
        padding: 0 0 1 0;
        border-bottom: solid #2a2a3e;
        height: auto;
    }

    #hub-content {
        height: 1fr;
        overflow-y: auto;
        padding: 1 0;
    }

    #hub-footer-box {
        align: center middle;
        height: auto;
        border-top: solid #1e1e2e;
        padding: 1 0 0 0;
    }

    #hub-close-btn {
        background: #FFD700;
        color: #000000;
        text-style: bold;
        border: none;
        height: 1;
        min-width: 24;
    }

    #hub-close-btn:hover {
        background: #F59E0B;
    }

    .hub-section-title {
        color: #FFD700;
        text-style: bold;
        padding: 1 0 0 0;
    }

    .hub-text {
        color: #e2e8f0;
    }

    .hub-muted {
        color: #94a3b8;
    }

    .hub-badge {
        color: #38bdf8;
    }

    .hub-cmd {
        color: #a855f7;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="hub-container"):
            yield Static("", id="hub-header")
            with ScrollableContainer(id="hub-content"):
                yield Static("", id="hub-body")
            with Container(id="hub-footer-box"):
                yield Button("CLOSE (Esc / Enter / Ctrl+M / Q)", id="hub-close-btn")

    def on_mount(self) -> None:
        self._render_header()
        self._render_body()

    def on_click(self, event) -> None:
        # Klik di area luar popup (backdrop gelap) langsung tutup modal!
        if event.widget == self:
            self.dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "hub-close-btn":
            self.dismiss()

    def _render_header(self) -> None:
        header = Text()
        header.append("VALLEN", style="bold #FFD700")
        header.append(" NEXSUS ", style="bold #b0a0ff")
        header.append("— CONTROL HUB & GUIDE", style="bold #f8fafc")
        header.append("\nAI Software Engineering Agent Terminal  ·  Press ESC or ENTER to return", style="italic #94a3b8")
        self.query_one("#hub-header", Static).update(header)

    def _render_body(self) -> None:
        cfg = get_config()
        ws = get_workspace()
        sess = get_session_manager()
        project_path = ws.active_project_path or os.getcwd()

        t = Text()

        # 1. STATUS & ENVIRONMENT
        t.append("─── CURRENT ENVIRONMENT & SETTINGS ───\n", style="bold #FFD700")
        t.append("  • Active Provider : ", style="#94a3b8")
        t.append(f"{cfg.active_provider}\n", style="bold #38bdf8")

        t.append("  • Main Model      : ", style="#94a3b8")
        t.append(f"{cfg.active_model or '(default)'}\n", style="bold #a855f7")

        sub_model = cfg.active_subagent_model
        t.append("  • Subagent Model  : ", style="#94a3b8")
        t.append(f"{sub_model or '(same as main model)'}\n", style="#818cf8")

        t.append("  • Base Endpoint   : ", style="#94a3b8")
        t.append(f"{cfg.active_base_url or 'http://127.0.0.1:20128/v1'}\n", style="#f1f5f9")

        t.append("  • Workspace Root  : ", style="#94a3b8")
        t.append(f"{project_path}\n", style="#f1f5f9")

        branch = get_git_branch_sync(project_path)
        if branch:
            t.append("  • Git Branch      : ", style="#94a3b8")
            t.append(f"{branch}\n", style="bold #22c55e")

        t.append("  • Active Session  : ", style="#94a3b8")
        t.append(f"{sess.title} [{sess.message_count} messages]\n\n", style="#f1f5f9")

        # 2. KEYBOARD SHORTCUTS
        t.append("─── KEYBOARD SHORTCUTS ───\n", style="bold #FFD700")
        shortcuts = [
            ("Esc / Enter / Q", "Close this Hub & Help popup"),
            ("Ctrl + M", "Open / close Control Hub & Settings"),
            ("Ctrl + P", "Open the model picker"),
            ("Ctrl + B", "Toggle the left sidebar"),
            ("Ctrl + N", "Start a new session (reset chat)"),
            ("Ctrl + S", "Open previous session history"),
            ("Ctrl + H", "Halt the running AI process"),
            ("Ctrl + D", "Exit VALLEN CLI"),
            ("Shift + Enter", "Insert a new line in chat"),
        ]
        for key, desc in shortcuts:
            t.append(f"  {key:<18}", style="bold #38bdf8")
            t.append(f"{desc}\n", style="#e2e8f0")
        t.append("\n")

        # 3. WORKSPACE & SYSTEM COMMANDS
        t.append("─── SLASH & WORKSPACE COMMANDS ───\n", style="bold #FFD700")
        sys_cmds = [
            ("/cd <path>", "Open a folder and activate its workspace"),
            ("/models", "Switch the AI model (or press Ctrl+P)"),
            ("/projects", "List all registered workspaces"),
            ("/sessions", "View sessions in this project"),
            ("/new", "Start a new session conversation"),
            ("/clear", "Clear the active conversation"),
            ("/compact", "Summarize the session to save context tokens"),
            ("/diff", "View file changes in this session"),
            ("/revert", "Roll back files to their initial state"),
            ("/mcp", "Manage Model Context Protocol servers"),
            ("/export", "Export the conversation to a Markdown file"),
            ("/agents", "View / edit AGENTS.md instructions"),
            ("/tokens", "Check current token usage"),
        ]
        for cmd, desc in sys_cmds:
            t.append(f"  {cmd:<22}", style="bold #a855f7")
            t.append(f"{desc}\n", style="#e2e8f0")
        t.append("\n")

        # 4. CUSTOM COMMANDS (OPENCODE MIRROR)
        custom_cmds = load_custom_commands(project_path)
        if custom_cmds:
            t.append("─── CUSTOM COMMANDS (OPENCODE COMPATIBLE) ───\n", style="bold #FFD700")
            for name, item in sorted(custom_cmds.items()):
                t.append(f"  /{name:<15}", style="bold #eab308")
                t.append(f"{item.get('description', '')}\n", style="#e2e8f0")
            t.append("\n")

        # 5. SPECIALIZED SKILLS
        skills = get_skills(project_path)
        if skills:
            t.append("─── ACTIVE SPECIALIZED SKILLS ───\n", style="bold #FFD700")
            for name, sk in sorted(skills.items()):
                t.append(f"  /{name:<15}", style="bold #06b6d4")
                t.append(f"{sk.description}\n", style="#cbd5e1")
            t.append("\n")

        # 6. QUICK SYNTAX
        t.append("─── QUICK SYNTAX ───\n", style="bold #FFD700")
        t.append("  @file.py          ", style="bold #ec4899")
        t.append("Inject file contents into the AI prompt\n", style="#e2e8f0")
        t.append("  !git status       ", style="bold #ec4899")
        t.append("Run a shell command directly without AI\n", style="#e2e8f0")

        self.query_one("#hub-body", Static).update(t)
