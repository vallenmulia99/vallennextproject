"""Small persistent token/cost ledger for agent runs."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workspace import get_workspace


def _path() -> Path:
    root = get_workspace().active_project_path or os.getcwd()
    return Path(root) / ".vallen" / "usage.json"


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_path().read_text())
        return data if isinstance(data, dict) else {"runs": []}
    except (OSError, json.JSONDecodeError):
        return {"runs": []}


def record_usage(*, kind: str, model: str, input_tokens: int, output_tokens: int, rounds: int = 1) -> dict[str, Any]:
    data = _load()
    run = {
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "model": model,
        "input_tokens": max(0, int(input_tokens)),
        "output_tokens": max(0, int(output_tokens)),
        "rounds": max(0, int(rounds)),
    }
    data.setdefault("runs", []).append(run)
    data["runs"] = data["runs"][-500:]
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".usage.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return run


def usage_summary() -> dict[str, int]:
    runs = _load().get("runs", [])
    return {
        "runs": len(runs),
        "input_tokens": sum(int(run.get("input_tokens", 0)) for run in runs),
        "output_tokens": sum(int(run.get("output_tokens", 0)) for run in runs),
        "rounds": sum(int(run.get("rounds", 0)) for run in runs),
    }


def usage_breakdown() -> dict[str, dict[str, int]]:
    """Aggregate usage by kind and model."""
    result: dict[str, dict[str, int]] = {}
    for run in _load().get("runs", []):
        key = f"{run.get('kind', 'unknown')}:{run.get('model', 'unknown')}"
        bucket = result.setdefault(key, {"runs": 0, "input_tokens": 0, "output_tokens": 0, "rounds": 0})
        bucket["runs"] += 1
        bucket["input_tokens"] += int(run.get("input_tokens", 0))
        bucket["output_tokens"] += int(run.get("output_tokens", 0))
        bucket["rounds"] += int(run.get("rounds", 0))
    return result
