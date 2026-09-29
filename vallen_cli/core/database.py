"""VALLEN CLI — SQLite session/history database."""

from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DB_FILE, ensure_config_dirs


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    ensure_config_dirs()
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id          TEXT PRIMARY KEY,
                project     TEXT NOT NULL DEFAULT '',
                title       TEXT NOT NULL DEFAULT 'New Session',
                model       TEXT NOT NULL DEFAULT '',
                provider    TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                tool_calls  TEXT,
                tool_call_id TEXT,
                name         TEXT,
                content_is_json INTEGER DEFAULT 0,
                created_at   TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id);

            CREATE INDEX IF NOT EXISTS idx_sessions_project
                ON sessions(project);
        """)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "tool_call_id" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN tool_call_id TEXT")
        if "name" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN name TEXT")
        if "content_is_json" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN content_is_json INTEGER DEFAULT 0")


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

class SessionDB:
    """High-level interface to session storage."""

    def create_session(
        self,
        project: str = "",
        title: str = "New Session",
        model: str = "",
        provider: str = "",
    ) -> str:
        import uuid
        sid = str(uuid.uuid4())
        now = _now_iso()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                (sid, project, title, model, provider, now, now),
            )
        return sid

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_sessions(self, project: str = "") -> list[dict[str, Any]]:
        with _connect() as conn:
            if project:
                rows = conn.execute(
                    "SELECT * FROM sessions WHERE project=? ORDER BY updated_at DESC",
                    (project,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sessions ORDER BY updated_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def update_session(self, session_id: str, **kwargs: Any) -> None:
        kwargs["updated_at"] = _now_iso()
        fields = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [session_id]
        with _connect() as conn:
            conn.execute(
                f"UPDATE sessions SET {fields} WHERE id=?", values
            )

    def delete_session(self, session_id: str) -> None:
        with _connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    def rename_session(self, session_id: str, title: str) -> None:
        self.update_session(session_id, title=title)

    # -- Messages -----------------------------------------------------------

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Any = None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> int:
        now = _now_iso()
        tc = json.dumps(tool_calls) if tool_calls is not None else None
        is_json = isinstance(content, (list, dict))
        stored_content = json.dumps(content) if is_json else content
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, name, content_is_json, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (session_id, role, stored_content, tc, tool_call_id, name, int(is_json), now),
            )
            row_id = cur.lastrowid
        self.update_session(session_id)
        return row_id

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
        result = []
        for r in rows:
            m = dict(r)
            if m["tool_calls"]:
                m["tool_calls"] = json.loads(m["tool_calls"])
            # Use explicit flag instead of heuristic
            if m.get("content_is_json") and m["content"]:
                try:
                    m["content"] = json.loads(m["content"])
                except Exception:
                    pass  # Keep as string if parse fails
            result.append(m)
        return result

    def clear_messages(self, session_id: str) -> None:
        with _connect() as conn:
            conn.execute(
                "DELETE FROM messages WHERE session_id=?", (session_id,)
            )

    def last_session_for_project(self, project: str) -> dict[str, Any] | None:
        sessions = self.list_sessions(project=project)
        # Prioritize the most recent session that actually has messages
        for s in sessions:
            with _connect() as conn:
                row = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (s["id"],)).fetchone()
                if row and row[0] > 0:
                    return s
        return sessions[0] if sessions else None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_session_db: SessionDB | None = None


def get_session_db() -> SessionDB:
    global _session_db
    if _session_db is None:
        init_db()
        _session_db = SessionDB()
    return _session_db
