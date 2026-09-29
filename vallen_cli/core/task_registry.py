"""Persistent subagent task registry and artifact index."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workspace import get_workspace


def _task_dir() -> Path:
    root = get_workspace().active_project_path or os.getcwd()
    return Path(root) / ".vallen" / "tasks"


def _index_path() -> Path:
    return _task_dir() / "index.json"


def _load() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(_index_path().read_text())
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(tasks: dict[str, dict[str, Any]]) -> None:
    directory = _task_dir()
    directory.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".index.", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(tasks, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, _index_path())
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def record_task(task_id: str, **fields: Any) -> dict[str, Any]:
    tasks = _load()
    current = tasks.get(task_id, {"task_id": task_id})
    current.update(fields)
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    tasks[task_id] = current
    _save(tasks)
    return current


def get_task(task_id: str) -> dict[str, Any] | None:
    return _load().get(task_id)


def list_tasks() -> list[dict[str, Any]]:
    return sorted(_load().values(), key=lambda item: item.get("updated_at", ""), reverse=True)


def recover_running_tasks() -> list[str]:
    """Mark tasks left running by a dead process as interrupted."""
    tasks = _load()
    recovered: list[str] = []
    for task_id, task in tasks.items():
        if task.get("status") == "running":
            task["status"] = "interrupted"
            task["error"] = "Process ended before task completed"
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            recovered.append(task_id)
    if recovered:
        _save(tasks)
    return recovered


def save_task_messages(task_id: str, messages: list[dict[str, Any]]) -> None:
    directory = _task_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{task_id}.json"
    fd, temp_name = tempfile.mkstemp(prefix=f".{task_id}.", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(messages, handle, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_task_messages(task_id: str) -> list[dict[str, Any]] | None:
    try:
        data = json.loads((_task_dir() / f"{task_id}.json").read_text())
        return data if isinstance(data, list) else None
    except (OSError, json.JSONDecodeError):
        return None


def cancel_task(task_id: str) -> bool:
    task = get_task(task_id)
    if not task or task.get("status") in {"completed", "failed", "cancelled"}:
        return False
    record_task(task_id, status="cancelled", error="Cancelled by user")
    return True
