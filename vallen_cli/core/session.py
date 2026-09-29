"""VALLEN CLI — Active session state and message history manager."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .database import get_session_db
from .config import get_config
from .workspace import get_workspace
from ..providers.base import Message


def _group_sessions_by_date(sessions: list[dict]) -> dict[str, list[dict]]:
    """Group sessions into Today / Yesterday / Older buckets."""
    now = datetime.now(timezone.utc)
    groups: dict[str, list[dict]] = {"Today": [], "Yesterday": [], "Older": []}
    for s in sessions:
        try:
            updated = datetime.fromisoformat(s["updated_at"])
            delta = (now - updated).days
            if delta == 0:
                groups["Today"].append(s)
            elif delta == 1:
                groups["Yesterday"].append(s)
            else:
                groups["Older"].append(s)
        except Exception:
            groups["Older"].append(s)
    return groups


class SessionManager:
    """
    Manages the in-memory state of the active conversation session,
    bridging WorkspaceManager ↔ SessionDB ↔ providers.
    """

    def __init__(self) -> None:
        self._db = get_session_db()
        self._ws = get_workspace()
        self._messages: list[Message] = []
        self._session_id: str | None = None
        self._title: str = "New Session"
        self._cached_system_prompt: str | None = None
        self.mode: str = "build"  # "build" | "plan"

    @property
    def cached_system_prompt(self) -> str | None:
        return self._cached_system_prompt

    @cached_system_prompt.setter
    def cached_system_prompt(self, val: str | None) -> None:
        self._cached_system_prompt = val

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_new(self) -> str:
        """Create a new session and return its ID."""
        cfg = get_config()
        sid = self._db.create_session(
            project=self._ws.active_project_path,
            title="New Session",
            model=cfg.active_model,
            provider=cfg.active_provider,
        )
        self._session_id = sid
        self._ws.active_session_id = sid
        self._messages = []
        self._title = "New Session"
        self._cached_system_prompt = None
        try:
            from ..tools.file_tools import clear_read_cache
            clear_read_cache()
        except ImportError:
            pass
        return sid

    def resume(self, session_id: str) -> bool:
        """Load an existing session from the DB."""
        session = self._db.get_session(session_id)
        if not session:
            return False
        self._session_id = session_id
        self._ws.active_session_id = session_id
        self._title = session.get("title", "Session")
        # Reconstruct Message objects
        raw = self._db.get_messages(session_id)
        self._messages = [
            Message(
                role=m["role"],
                content=m["content"],
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
            )
            for m in raw
            if m["role"] != "system"  # system prompt rebuilt fresh each call
        ]
        return True

    def resume_last(self) -> str:
        """Resume last session or create new one."""
        last = self._db.last_session_for_project(self._ws.active_project_path)
        if last:
            self.resume(last["id"])
            return last["id"]
        return self.start_new()

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def title(self) -> str:
        return self._title

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def add_user_message(self, content: str | list[dict[str, Any]]) -> None:
        msg = Message(role="user", content=content)
        self._messages.append(msg)
        if self._session_id:
            self._db.add_message(self._session_id, "user", content)
        self._maybe_auto_title(content)

    def add_assistant_message(self, content: str | list[dict[str, Any]], tool_calls: Any = None) -> None:
        msg = Message(role="assistant", content=content, tool_calls=tool_calls)
        self._messages.append(msg)
        if self._session_id:
            self._db.add_message(self._session_id, "assistant", content, tool_calls)

    def add_tool_result(self, tool_call_id: str, name: str, content: str | list[dict[str, Any]]) -> None:
        msg = Message(role="tool", content=content, tool_call_id=tool_call_id, name=name)
        self._messages.append(msg)
        if self._session_id:
            self._db.add_message(self._session_id, "tool", content, tool_call_id=tool_call_id, name=name)

    def get_api_messages(self) -> list[Message]:
        """Return messages ready to send to the LLM, with system prompt prepended."""
        cfg = get_config()
        system = Message(role="system", content=cfg.system_prompt)
        return [system] + self._messages

    def clear(self) -> None:
        self._messages = []
        self._cached_system_prompt = None
        if self._session_id:
            self._db.clear_messages(self._session_id)
        try:
            from ..tools.file_tools import clear_read_cache
            clear_read_cache()
        except ImportError:
            pass

    @property
    def message_count(self) -> int:
        return len(self._messages)

    # ------------------------------------------------------------------
    # Session listing helpers
    # ------------------------------------------------------------------

    def list_grouped(self) -> dict[str, list[dict]]:
        sessions = self._db.list_sessions(self._ws.active_project_path)
        return _group_sessions_by_date(sessions)

    def list_all_for_project(self) -> list[dict]:
        return self._db.list_sessions(self._ws.active_project_path)

    # ------------------------------------------------------------------
    # Auto-title
    # ------------------------------------------------------------------

    def _maybe_auto_title(self, user_message: Any) -> None:
        """Set session title from the first user message if still default."""
        if self._title != "New Session" or not self._session_id:
            return
        if isinstance(user_message, list):
            texts = [b.get("text", "") for b in user_message if isinstance(b, dict) and b.get("type") == "text"]
            text_str = " ".join(texts) or "Attachment"
        else:
            text_str = str(user_message)
        words = text_str.strip().split()
        title = " ".join(words[:8])
        if len(words) > 8:
            title += "…"
        title = title[:60] or "Session"
        self._title = title
        self._db.rename_session(self._session_id, title)


# Singleton
_session_mgr: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _session_mgr
    if _session_mgr is None:
        _session_mgr = SessionManager()
    return _session_mgr
