"""VALLEN CLI — Permission confirmation modal.

Inspired by opencode/src/permission/index.ts.
Shows when agent wants to write files or run shell commands.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static, ListView, ListItem, Label
from textual.widget import Widget
from rich.text import Text

from ...core.permission import PermRequest, PermReply


class PermissionModal(ModalScreen):
    """Ask user to allow/reject a tool operation."""

    BINDINGS = [
        Binding("escape", "reject", "Reject"),
        Binding("y", "allow_once", "Allow once"),
        Binding("a", "allow_always", "Always allow this target"),
        Binding("e", "allow_all_edits", "Always allow edits this session"),
        Binding("n", "reject", "Reject"),
    ]

    CSS = """
    PermissionModal {
        align: center middle;
        background: #000000 60%;
    }
    #pm-box {
        width: 64;
        height: auto;
        background: #131320;
        border: solid #ff9944;
        padding: 1 2;
    }
    #pm-title {
        color: #ff9944;
        text-style: bold;
        text-align: center;
        padding: 0 0 1 0;
    }
    #pm-tool {
        color: #f0f0f5;
        text-style: bold;
        padding: 0 0 0 0;
    }
    #pm-desc {
        color: #c8c8e8;
        padding: 0 0 1 0;
    }
    #pm-list {
        height: auto;
        background: #131320;
        border: none;
        padding: 0;
    }
    #pm-hint {
        color: #666688;
        text-align: center;
        padding: 1 0 0 0;
    }
    PermOption {
        height: 1;
        padding: 0 1;
        background: #131320;
    }
    PermOption:hover {
        background: #1e1e38;
    }
    PermOption.--highlight {
        background: #1e1e38;
    }
    """

    def __init__(self, request: PermRequest) -> None:
        super().__init__()
        self._request = request
        self._reply: PermReply = PermReply.REJECT

    def compose(self) -> ComposeResult:
        is_file_edit = self._request.tool_name in {"write", "write_file", "edit", "edit_file", "apply_patch"}
        with Widget(id="pm-box"):
            yield Static("⚠  PERMISSION REQUEST", id="pm-title")
            yield Static(Text(f"  Tool: {self._request.tool_name}", style="bold #ffaa44"), id="pm-tool")
            yield Static(Text(f"  {self._request.description}", style="#c8c8e8"), id="pm-desc")
            if getattr(self._request, "preview", ""):
                yield Static(Text(f"  Preview:\n{self._request.preview[:800]}", style="#88cc88"), id="pm-preview")
            options = [
                ListItem(PermOption("y", "Allow once", "#66dd88", "allow this operation")),
                ListItem(PermOption("a", "Always this target", "#9b88ff", "remember this file or command for this session")),
            ]
            if is_file_edit:
                options.append(ListItem(PermOption("e", "All edits this session", "#77bbff", "allow write, edit, and patch; shell still asks")))
            options.append(ListItem(PermOption("n", "Reject", "#ff6666", "deny and tell the agent")))
            yield ListView(*options, id="pm-list")
            hint = "[#555577]y[/] once   [#555577]a[/] this target"
            if is_file_edit:
                hint += "   [#555577]e[/] all edits"
            yield Static(hint + "   [#555577]n/Esc[/] reject", id="pm-hint")

    def on_mount(self) -> None:
        self.query_one("#pm-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx == 0:
            self.action_allow_once()
        elif idx == 1:
            self.action_allow_always()
        elif self._request.tool_name in {"write", "write_file", "edit", "edit_file", "apply_patch"} and idx == 2:
            self.action_allow_all_edits()
        else:
            self.action_reject()

    def action_allow_once(self) -> None:
        self.dismiss(PermReply.ONCE)

    def action_allow_always(self) -> None:
        self.dismiss(PermReply.ALWAYS)

    def action_allow_all_edits(self) -> None:
        if self._request.tool_name in {"write", "write_file", "edit", "edit_file", "apply_patch"}:
            self.dismiss(PermReply.ALWAYS_EDITS)

    def action_reject(self) -> None:
        self.dismiss(PermReply.REJECT)


class PermOption(Widget):
    DEFAULT_CSS = "PermOption { height: 1; padding: 0 1; }"

    def __init__(self, key: str, label: str, color: str, sub: str) -> None:
        super().__init__()
        self._key = key
        self._label = label
        self._color = color
        self._sub = sub

    def compose(self) -> ComposeResult:
        t = Text()
        t.append(f"  [{self._key}] ", style=f"bold {self._color}")
        t.append(self._label, style=f"bold {self._color}")
        t.append(f"  — {self._sub}", style="#888899")
        yield Static(t)
