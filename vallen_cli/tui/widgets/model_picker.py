"""VALLEN CLI — Model picker modal (Ctrl+P)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static
from textual.widget import Widget

from ...providers.registry import get_registry
from ...core.config import get_config


class ModelPickerScreen(ModalScreen):
    """Full-screen overlay for selecting provider + model."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("ctrl+p", "dismiss", "Close"),
    ]

    CSS = """
    ModelPickerScreen {
        align: center middle;
        background: #000000 70%;
    }
    #mp-container {
        width: 62;
        height: auto;
        background: #131320;
        border: solid #3a3a5a;
        padding: 1 2;
    }
    #mp-title {
        color: #7b68ee;
        text-style: bold;
        text-align: center;
        padding: 0 0 1 0;
    }
    #mp-search {
        background: #0d0d18;
        color: #e0e0e6;
        border: solid #2a2a44;
        margin: 0 0 1 0;
        height: 3;
    }
    #mp-search:focus {
        border: solid #7b68ee;
    }
    #mp-list {
        height: auto;
        background: #131320;
        border: none;
        padding: 0;
    }
    #mp-hint {
        color: #9090bb;
        text-align: center;
        padding: 1 0 0 0;
    }
    ModelPickerItem {
        background: #131320;
        height: 2;
        padding: 0 1;
    }
    ModelPickerItem:hover {
        background: #1e1e38;
    }
    ModelPickerItem.--highlight {
        background: #1e1e38;
    }
    .mpi-model {
        color: #9999cc;
        text-style: bold;
    }
    .mpi-provider {
        color: #9090aa;
    }
    .mpi-check {
        color: #7b68ee;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._all_items: list[tuple[str, str, str]] = []  # (provider, model_id, display)
        self._filtered: list[tuple[str, str, str]] = []

    def compose(self) -> ComposeResult:
        with Widget(id="mp-container"):
            yield Static("SELECT MODEL", id="mp-title")
            yield Input(placeholder="Search models...", id="mp-search")
            yield ListView(id="mp-list")
            yield Static("↑↓ navigate   Enter select   Esc close", id="mp-hint")

    def on_mount(self) -> None:
        self._load_models()
        self.query_one("#mp-search", Input).focus()

    def _load_models(self) -> None:
        registry = get_registry()
        cfg = get_config()
        current_model = cfg.active_model
        current_provider = cfg.active_provider
        items: list[tuple[str, str, str]] = []

        for name, provider in registry.all():
            display = registry.display_name(name)
            p_models = cfg.get("providers", name, "models", default=[])
            if isinstance(p_models, list) and p_models:
                for m in p_models:
                    if m:
                        items.append((name, m, display))
            else:
                model = provider.config.model
                if model:
                    items.append((name, model, display))

        self._all_items = items
        self._filtered = list(items)
        self._rebuild_list(current_provider, current_model)

    def _rebuild_list(self, current_provider: str = "", current_model: str = "", query: str = "") -> None:
        lst = self.query_one("#mp-list", ListView)
        lst.clear()

        q = query.lower()
        filtered = [
            (prov, model, disp)
            for prov, model, disp in self._all_items
            if not q or q in model.lower() or q in prov.lower()
        ]
        self._filtered = filtered

        for prov, model, disp in filtered:
            is_active = (prov == current_provider and model == current_model)
            item = ListItem(ModelPickerItem(prov, model, disp, is_active))
            lst.append(item)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "mp-search":
            cfg = get_config()
            self._rebuild_list(cfg.active_provider, cfg.active_model, event.value)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        items = event.list_view.query(ModelPickerItem)
        item_list = list(items)
        idx = event.list_view.index
        if 0 <= idx < len(self._filtered):
            prov, model, _ = self._filtered[idx]
            cfg = get_config()
            registry = get_registry()
            cfg.active_provider = prov
            cfg.active_model = model
            cfg.save()
            registry.reload()
            self.dismiss({"provider": prov, "model": model})

    def action_dismiss(self) -> None:
        self.dismiss(None)


class ModelPickerItem(Widget):
    """A single row in the model picker list."""

    DEFAULT_CSS = """
    ModelPickerItem {
        layout: vertical;
        height: 2;
        padding: 0 1;
    }
    """

    def __init__(self, provider: str, model: str, display: str, active: bool = False) -> None:
        super().__init__()
        self._provider = provider
        self._model = model
        self._display = display
        self._active = active

    def compose(self) -> ComposeResult:
        from rich.text import Text
        check = "✓ " if self._active else "  "
        model_text = Text()
        model_text.append(check, style="#7b68ee" if self._active else "#9090aa")
        model_text.append(self._model, style="bold #9999cc" if self._active else "#888899")
        yield Static(model_text)
        yield Static(self._display, classes="mpi-provider")
