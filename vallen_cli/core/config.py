"""VALLEN CLI — Configuration management."""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

import toml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFIG_DIR = Path(os.environ.get("VALLEN_CONFIG_DIR", "~/.config/vallen")).expanduser()
CONFIG_FILE = CONFIG_DIR / "config.toml"
PROJECTS_FILE = CONFIG_DIR / "projects.json"
SESSIONS_DIR = CONFIG_DIR / "sessions"
HISTORY_DIR = CONFIG_DIR / "history"
DB_FILE = CONFIG_DIR / "vallen.db"


def ensure_config_dirs() -> None:
    """Create all config directories if they don't exist."""
    for d in [CONFIG_DIR, SESSIONS_DIR, HISTORY_DIR]:
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        "theme": "dark",
        "system_prompt": (
            "You are VALLEN, an expert AI software engineering agent. "
            "You help developers write, review, debug, and improve code. "
            "Be concise, practical, and precise. When writing code, always "
            "include the full implementation without placeholders."
        ),
        # Coding agents need repeatable tool selection more than creative output.
        "temperature": 0.2,
        "max_tokens": 32768,
        "workspace": "",
    },
    "providers": {
        "active": "9router",
        "9router": {
            "base_url": "http://localhost:20128/v1",
            "api_key": "",
            "model": "ag/gemini-3.8-flash-medium",
            "enabled": True,
        },
        "vallennext": {
            "title": "VallenNext Free Coder",
            "base_url": "https://apikeyfreevallennext.vercel.app/v1",
            "api_key": "free",
            "model": "vallennext/free",
            "models": ["vallennext/free"],
            "enabled": True,
        },
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "model": "gpt-4o",
            "enabled": False,
        },
        "anthropic": {
            "base_url": "https://api.anthropic.com/v1",
            "api_key": "",
            "model": "claude-3-5-sonnet-20241022",
            "enabled": False,
        },
        "gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "",
            "model": "gemini-2.0-flash",
            "enabled": False,
        },
    },
    "ui": {
        "show_sidebar": True,
        "show_context_panel": True,
        "compact_mode": False,
        "syntax_highlight": True,
        "stream_responses": True,
    },
}


# ---------------------------------------------------------------------------
# Config loader/saver
# ---------------------------------------------------------------------------

class Config:
    """Application configuration backed by TOML file."""

    def __init__(self) -> None:
        ensure_config_dirs()
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load config from disk, merging with defaults."""
        self._data = _deep_merge(DEFAULT_CONFIG, {})
        if CONFIG_FILE.exists():
            try:
                file_data = toml.loads(CONFIG_FILE.read_text())
                self._data = _deep_merge(self._data, file_data)
            except Exception:
                pass  # Fall back to defaults silently

        # Auto-detect models.json in project or config dir
        for candidate in [
            Path(".vallen/models.json"),
            Path("models.json"),
            CONFIG_DIR / "models.json",
        ]:
            if candidate.exists():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    for m in data.get("models", []):
                        m_id = m.get("model", "")
                        if not m_id:
                            continue
                        p_name = m.get("provider") or m_id.split("/")[0] or "openai"
                        if "vallennext" in m_id or "vallennext" in str(m.get("apiBase", "")):
                            prov_key = "vallennext"
                        elif p_name in ("openai", "anthropic", "gemini", "ollama") and (m.get("apiBase") or m.get("base_url")):
                            prov_key = f"{p_name}_{m_id.replace('/', '_')}"
                        else:
                            prov_key = p_name

                        prov_cfg = self._data.setdefault("providers", {}).setdefault(prov_key, {})
                        if m.get("title"):
                            prov_cfg["title"] = m["title"]
                        base_url = m.get("apiBase") or m.get("base_url")
                        if base_url:
                            prov_cfg["base_url"] = base_url
                        api_key = m.get("apiKey") or m.get("api_key")
                        if api_key:
                            prov_cfg["api_key"] = api_key
                        prov_cfg["model"] = m_id
                        prov_models = prov_cfg.setdefault("models", [])
                        if m_id not in prov_models:
                            prov_models.append(m_id)
                        prov_cfg["enabled"] = True
                except Exception:
                    pass

    def save(self) -> None:
        """Persist config to disk."""
        CONFIG_FILE.write_text(toml.dumps(self._data))

    def get(self, *keys: str, default: Any = None) -> Any:
        """Dot-path access: config.get('providers', '9router', 'model')."""
        node = self._data
        for k in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(k, default)
        return node

    def set(self, *keys_and_value: Any) -> None:
        """Set a nested key. Last arg is the value."""
        *keys, value = keys_and_value
        node = self._data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value

    # -- Convenience properties ------------------------------------------

    @property
    def active_provider(self) -> str:
        return self.get("providers", "active", default="9router")

    @active_provider.setter
    def active_provider(self, name: str) -> None:
        self.set("providers", "active", name)
        self.save()

    @property
    def active_model(self) -> str:
        provider = self.active_provider
        return self.get("providers", provider, "model", default="")

    @active_model.setter
    def active_model(self, model: str) -> None:
        provider = self.active_provider
        self.set("providers", provider, "model", model)
        self.save()

    @property
    def active_subagent_model(self) -> str:
        provider = self.active_provider
        return self.get("providers", provider, "subagent_model", default="")

    @active_subagent_model.setter
    def active_subagent_model(self, model: str) -> None:
        provider = self.active_provider
        self.set("providers", provider, "subagent_model", model)
        self.save()

    @property
    def active_provider_models(self) -> list[str]:
        provider = self.active_provider
        models = self.get("providers", provider, "models", default=[])
        if isinstance(models, list) and models:
            return models
        single = self.get("providers", provider, "model", default="")
        return [single] if single else []

    @property
    def active_base_url(self) -> str:
        provider = self.active_provider
        return self.get("providers", provider, "base_url", default="")

    @property
    def active_api_key(self) -> str:
        provider = self.active_provider
        return self.get("providers", provider, "api_key", default="")

    @property
    def system_prompt(self) -> str:
        return self.get("general", "system_prompt", default="")

    @property
    def temperature(self) -> float:
        return float(self.get("general", "temperature", default=0.7))

    @property
    def max_tokens(self) -> int:
        return int(self.get("general", "max_tokens", default=8192))

    @property
    def stream_responses(self) -> bool:
        return bool(self.get("ui", "stream_responses", default=True))

    def provider_config(self, name: str) -> dict[str, Any]:
        return self.get("providers", name, default={})

    def all_providers(self) -> list[tuple[str, dict[str, Any]]]:
        providers = self._data.get("providers", {})
        return [
            (k, v)
            for k, v in providers.items()
            if isinstance(v, dict) and k != "active"
        ]


# ---------------------------------------------------------------------------
# Projects persistence
# ---------------------------------------------------------------------------

class ProjectsDB:
    """Simple JSON-backed projects store."""

    def __init__(self) -> None:
        ensure_config_dirs()
        self._file = PROJECTS_FILE
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self._file.exists():
            try:
                return json.loads(self._file.read_text())
            except Exception:
                pass
        return {"projects": {}, "active": None}

    def _save(self) -> None:
        self._file.write_text(json.dumps(self._data, indent=2))

    def add_project(self, path: str, name: str | None = None) -> dict[str, Any]:
        abs_path = str(Path(path).expanduser().resolve())
        if not name:
            name = Path(abs_path).name
        project = {
            "name": name,
            "path": abs_path,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        self._data["projects"][abs_path] = project
        self._save()
        return project

    def get_project(self, path: str) -> dict[str, Any] | None:
        abs_path = str(Path(path).expanduser().resolve())
        return self._data["projects"].get(abs_path)

    def get_project_by_name(self, name: str) -> dict[str, Any] | None:
        for p in self._data["projects"].values():
            if p["name"] == name:
                return p
        return None

    def all_projects(self) -> list[dict[str, Any]]:
        self._data = self._load()
        projs = list(self._data.get("projects", {}).values())
        return sorted(projs, key=lambda p: p.get("updated_at") or "", reverse=True)

    def clear_all(self) -> None:
        self._data["projects"] = {}
        self._data["active"] = None
        self._save()

    def set_active(self, path: str) -> None:
        abs_path = str(Path(path).expanduser().resolve())
        self._data["active"] = abs_path
        if abs_path in self._data["projects"]:
            self._data["projects"][abs_path]["updated_at"] = _now_iso()
        self._save()

    def get_active(self) -> dict[str, Any] | None:
        active = self._data.get("active")
        if active:
            return self._data["projects"].get(active)
        return None

    def remove_project(self, path: str) -> bool:
        abs_path = str(Path(path).expanduser().resolve())
        if abs_path in self._data["projects"]:
            del self._data["projects"][abs_path]
            if self._data.get("active") == abs_path:
                self._data["active"] = None
            self._save()
            return True
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    import copy
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Singleton accessors
# ---------------------------------------------------------------------------

_config: Config | None = None
_projects_db: ProjectsDB | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


def get_projects_db() -> ProjectsDB:
    global _projects_db
    if _projects_db is None:
        _projects_db = ProjectsDB()
    return _projects_db
