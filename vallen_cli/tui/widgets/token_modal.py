"""VALLEN CLI — 9Router API Token Modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from ...core.config import get_config
from ...providers.registry import get_registry


class TokenModal(ModalScreen):
    """Modal for setting the 9Router API token and endpoint."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
    ]

    CSS = """
    TokenModal {
        align: center middle;
        background: #000000 80%;
    }
    #tm-container {
        width: 64;
        height: auto;
        background: #0e0e14;
        border: solid #FFD700;
        padding: 1 2;
    }
    #tm-title {
        text-align: center;
        color: #FFD700;
        text-style: bold;
        padding: 0 0 1 0;
        border-bottom: solid #2a2a3e;
    }
    #tm-body {
        padding: 1 0;
    }
    .tm-label {
        color: #94a3b8;
        margin: 1 0 0 0;
    }
    .tm-input {
        background: #0d0d18;
        color: #e0e0e6;
        border: solid #2a2a44;
        height: 3;
        margin: 0 0 0 0;
    }
    .tm-input:focus {
        border: solid #FFD700;
    }
    #tm-status {
        color: #22c55e;
        text-align: center;
        height: 1;
        margin: 1 0 0 0;
    }
    #tm-btn-row {
        align: center middle;
        height: auto;
        margin: 1 0 0 0;
    }
    #tm-save-btn {
        background: #FFD700;
        color: #000000;
        text-style: bold;
        border: none;
        height: 1;
        min-width: 16;
        margin: 0 1;
    }
    #tm-save-btn:hover {
        background: #F59E0B;
    }
    #tm-cancel-btn {
        background: #2a2a3e;
        color: #94a3b8;
        border: none;
        height: 1;
        min-width: 16;
        margin: 0 1;
    }
    #tm-cancel-btn:hover {
        background: #3a3a5e;
        color: #e2e8f0;
    }
    """

    def compose(self) -> ComposeResult:
        cfg = get_config()
        current_key = cfg.get("providers", "9router", "api_key", default="")
        current_url = cfg.get("providers", "9router", "base_url", default="http://localhost:20128/v1")
        current_model = cfg.get("providers", "9router", "model", default="ag/gemini-3.8-flash-medium")

        with Container(id="tm-container"):
            yield Static("9ROUTER — TOKEN & ENDPOINT", id="tm-title")
            with Container(id="tm-body"):
                yield Label("API Token (api_key):", classes="tm-label")
                yield Input(
                    value=current_key,
                    placeholder="Paste 9Router token here...",
                    password=True,
                    id="tm-key",
                    classes="tm-input",
                )
                yield Label("Base URL:", classes="tm-label")
                yield Input(
                    value=current_url,
                    placeholder="http://localhost:20128/v1",
                    id="tm-url",
                    classes="tm-input",
                )
                yield Label("Model:", classes="tm-label")
                yield Input(
                    value=current_model,
                    placeholder="ag/gemini-3.8-flash-medium",
                    id="tm-model",
                    classes="tm-input",
                )
                yield Static("", id="tm-status")
            with Container(id="tm-btn-row"):
                yield Button("SAVE & ACTIVATE", id="tm-save-btn")
                yield Button("Cancel", id="tm-cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tm-cancel-btn":
            self.dismiss(None)
            return

        if event.button.id == "tm-save-btn":
            cfg = get_config()
            key = self.query_one("#tm-key", Input).value.strip()
            url = self.query_one("#tm-url", Input).value.strip()
            model = self.query_one("#tm-model", Input).value.strip()

            cfg.set("providers", "9router", "api_key", key)
            cfg.set("providers", "9router", "base_url", url or "http://localhost:20128/v1")
            cfg.set("providers", "9router", "model", model or "ag/gemini-3.8-flash-medium")
            cfg.set("providers", "9router", "enabled", True)
            cfg.active_provider = "9router"
            cfg.save()
            get_registry().reload()

            self.query_one("#tm-status", Static).update("✓ Saved! 9Router now active.")
            self.set_timer(1.2, lambda: self.dismiss({"saved": True}))

    def on_click(self, event) -> None:
        if event.widget == self:
            self.dismiss(None)
