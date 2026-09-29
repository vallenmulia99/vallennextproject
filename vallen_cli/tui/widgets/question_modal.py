"""VALLEN CLI — Question modal: agent asks user a question."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static
from textual.widget import Widget
from textual.message import Message
from rich.text import Text


class QuestionModal(ModalScreen):
    """Popup shown when the agent calls the `question` tool."""

    BINDINGS = [
        Binding("escape", "skip", "Skip"),
    ]

    CSS = """
    QuestionModal {
        align: center middle;
        background: #000000 60%;
    }
    #qm-box {
        width: 70;
        height: auto;
        background: #131320;
        border: solid #9b88ff;
        padding: 1 2;
    }
    #qm-title {
        color: #9b88ff;
        text-style: bold;
        text-align: center;
        padding: 0 0 1 0;
    }
    #qm-question {
        color: #f0f0f5;
        padding: 0 0 1 0;
    }
    #qm-input {
        background: #0d0d18;
        color: #f0f0f5;
        border: solid #3a3a5a;
        margin: 0 0 1 0;
        height: 3;
    }
    #qm-input:focus {
        border: solid #9b88ff;
    }
    #qm-options {
        height: auto;
        background: #131320;
        border: none;
    }
    #qm-hint {
        color: #555577;
        text-align: center;
        padding: 1 0 0 0;
    }
    QOption {
        height: 1;
        padding: 0 1;
        background: #131320;
    }
    QOption:hover {
        background: #1e1e38;
    }
    QOption.--highlight {
        background: #1e1e38;
    }
    """

    def __init__(self, question: str, options: list[str] | None = None) -> None:
        super().__init__()
        self._question = question
        self._options  = options or []

    def compose(self) -> ComposeResult:
        with Widget(id="qm-box"):
            yield Static("VALLEN — Question", id="qm-title")
            yield Static(Text(f"  {self._question}", style="#f0f0f5"), id="qm-question")

            if self._options:
                items = [ListItem(QOption(i + 1, opt)) for i, opt in enumerate(self._options)]
                yield ListView(*items, id="qm-options")
                yield Static(
                    "↑↓ navigate   Enter select   or type below",
                    id="qm-hint",
                )
            else:
                yield Static(
                    "[#555577]Enter[/] to send   [#555577]Esc[/] to skip",
                    id="qm-hint",
                )

            yield Input(placeholder="Type your answer…", id="qm-input")

    def on_mount(self) -> None:
        if self._options:
            try:
                self.query_one("#qm-options", ListView).focus()
            except Exception:
                pass
        else:
            self.query_one("#qm-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        answer = event.value.strip()
        if answer:
            self.dismiss(answer)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if 0 <= idx < len(self._options):
            self.dismiss(self._options[idx])

    def action_skip(self) -> None:
        self.dismiss(None)


class QOption(Widget):
    DEFAULT_CSS = "QOption { height: 1; padding: 0 1; }"

    def __init__(self, n: int, text: str) -> None:
        super().__init__()
        self._n    = n
        self._text = text

    def compose(self) -> ComposeResult:
        t = Text()
        t.append(f"  {self._n}. ", style="#9b88ff bold")
        t.append(self._text, style="#f0f0f5")
        yield Static(t)
