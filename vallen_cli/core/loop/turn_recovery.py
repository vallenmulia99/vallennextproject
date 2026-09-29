"""VALLEN CLI — Loop recovery handling (truncation, provider retry, error classification)."""

from __future__ import annotations

from typing import Any, Callable
from ..error_classifier import classify_error, ErrorClassification


def handle_length_truncation(
    stream_finish_reason: str | None,
    current_count: int,
    max_retries: int,
    session: Any,
    on_event: Callable[[Any], None] | None = None,
    agent_event_cls: Any = None,
) -> bool:
    """If finish_reason == 'length' and within retry limit, inject continuation prompt and return True."""
    if stream_finish_reason == "length" and current_count < max_retries:
        if on_event and agent_event_cls:
            on_event(agent_event_cls("info", f"Balasan terpotong batas token (ke-{current_count + 1}), meminta lanjutan..."))
        session.add_user_message("Balasanmu terpotong batas token. Lanjutkan tepat dari titik berhenti.")
        return True
    return False


def should_retry_provider_error(
    error: Any,
    attempt: int,
    max_attempts: int = 3,
) -> tuple[bool, float, ErrorClassification]:
    """Determine whether a provider error should be retried based on classification."""
    classification = classify_error(error)
    if not classification.is_retryable or attempt >= max_attempts:
        return False, 0.0, classification

    backoff = classification.suggested_delay * (1.5 ** attempt)
    return True, backoff, classification
