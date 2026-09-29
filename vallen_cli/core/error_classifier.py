"""VALLEN CLI — Error Classification & Retry Policy (inspired by Hermes Agent)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorClassification:
    is_retryable: bool
    kind: str  # "rate_limit", "server_error", "timeout", "auth_error", "client_error", "unknown"
    status_code: int | None
    message: str
    suggested_delay: float = 1.0


_NON_RETRYABLE_STATUSES = {400, 401, 403, 404, 422}
_RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}


def classify_error(error: Any) -> ErrorClassification:
    """Classify an API or system error into actionable categories."""
    status_code: int | None = getattr(error, "status_code", None) or getattr(error, "code", None)
    err_str = str(error) if error else ""

    # Check for HTTP status code in message if not directly on object
    if status_code is None:
        match = re.search(r"\b([45]\d{2})\b", err_str)
        if match:
            try:
                status_code = int(match.group(1))
            except ValueError:
                pass

    if status_code in _NON_RETRYABLE_STATUSES:
        kind = "auth_error" if status_code in (401, 403) else "client_error"
        return ErrorClassification(
            is_retryable=False,
            kind=kind,
            status_code=status_code,
            message=err_str,
            suggested_delay=0.0,
        )

    if status_code == 429 or "rate limit" in err_str.lower() or "too many requests" in err_str.lower():
        delay = 2.0
        retry_after = re.search(r"retry[- ]after[:\s]+(\d+(?:\.\d+)?)", err_str, re.IGNORECASE)
        if retry_after:
            try:
                delay = float(retry_after.group(1))
            except ValueError:
                delay = 2.0
        return ErrorClassification(
            is_retryable=True,
            kind="rate_limit",
            status_code=429,
            message=err_str,
            suggested_delay=max(1.0, delay),
        )

    if (
        (status_code and status_code in (500, 502, 503, 504))
        or "bad gateway" in err_str.lower()
        or "service unavailable" in err_str.lower()
    ):
        return ErrorClassification(
            is_retryable=True,
            kind="server_error",
            status_code=status_code or 500,
            message=err_str,
            suggested_delay=1.5,
        )

    if "timeout" in err_str.lower() or "timed out" in err_str.lower() or "connection" in err_str.lower():
        return ErrorClassification(
            is_retryable=True,
            kind="timeout",
            status_code=status_code,
            message=err_str,
            suggested_delay=1.0,
        )

    return ErrorClassification(
        is_retryable=False,
        kind="unknown",
        status_code=status_code,
        message=err_str,
        suggested_delay=0.0,
    )
