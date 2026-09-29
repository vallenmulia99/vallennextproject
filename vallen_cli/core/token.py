"""VALLEN CLI — Token estimation and context overflow detection.

Logic inspired by opencode/src/util/token.ts and session/overflow.ts.
Uses simple tiktoken-free estimation: ~4 chars per token (works for all models).
"""

from __future__ import annotations

import json
from typing import Any

# ~4 chars per token — conservative estimate that works across all models
CHARS_PER_TOKEN = 4

# Default context limits per known model prefix
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "gpt-4o":               128_000,
    "gpt-4":                 128_000,
    "gpt-4.5":               128_000,
    "gpt-3.5":               16_000,
    "claude-3-5":           200_000,
    "claude-3":             200_000,
    "claude-4":             200_000,
    "claude-opus":          200_000,
    "claude-sonnet":        200_000,
    "claude-haiku":         200_000,
    "gemini-2.0":         1_000_000,
    "gemini-1.5":         1_000_000,
    "gemini-2.5":         1_000_000,
    "gemini-3":           1_000_000,
    "ag/gemini":          1_000_000,
    "deepseek":           128_000,
    "deepseek-coder":     128_000,
    "deepseek-r1":        128_000,
    "llama":               32_000,
}

# Fraction of context limit at which we trigger auto-compact
OVERFLOW_THRESHOLD = 0.85
# Reserve this many tokens for model output
OUTPUT_RESERVE = 8_192
# Minimum tokens before compact makes sense
PRUNE_MINIMUM = 20_000


def estimate(text: str) -> int:
    """Estimate token count from raw text. ~4 chars per token."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_messages(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens for a list of OpenAI-format messages."""
    return estimate(json.dumps(messages))


def context_limit(model_id: str) -> int:
    """Return estimated context window for a given model ID."""
    model_lower = model_id.lower()
    # Direct match against known prefixes
    for prefix, limit in MODEL_CONTEXT_LIMITS.items():
        if model_lower.startswith(prefix):
            return limit
    # Router-prefixed models like "cc/claude-sonnet-5-5": strip prefix and retry
    if "/" in model_lower:
        stripped = model_lower.split("/")[-1]
        for prefix, limit in MODEL_CONTEXT_LIMITS.items():
            if stripped.startswith(prefix):
                return limit
    return 128_000  # safe default


def usable_context(model_id: str) -> int:
    """How many input tokens we can use (reserves space for output)."""
    limit = context_limit(model_id)
    return max(0, limit - OUTPUT_RESERVE)


def is_overflow(token_count: int, model_id: str) -> bool:
    """True if token_count exceeds the overflow threshold for this model."""
    limit = usable_context(model_id)
    if limit == 0:
        return False
    return token_count >= int(limit * OVERFLOW_THRESHOLD)


def usage_percent(token_count: int, model_id: str) -> float:
    """Return usage as 0.0–1.0 fraction of usable context."""
    limit = usable_context(model_id)
    if limit == 0:
        return 0.0
    return min(1.0, token_count / limit)


def format_usage(token_count: int, model_id: str) -> str:
    """Return a compact display string: '12.4k / 128k (10%)'"""
    pct = usage_percent(token_count, model_id) * 100
    limit = usable_context(model_id)

    def _fmt(n: int) -> str:
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}k"
        return str(n)

    return f"{_fmt(token_count)} / {_fmt(limit)} ({pct:.0f}%)"
