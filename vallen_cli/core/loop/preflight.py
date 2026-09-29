"""VALLEN CLI — Loop preflight checks (cancellation, context budgeting, compaction)."""

from __future__ import annotations

import asyncio
from typing import Any, Callable
from ..compact import should_compact, compact_session
from ..token import format_usage


def check_cancellation(
    cancel_event: asyncio.Event | None,
    session: Any,
    pending_tool_calls: list[dict[str, Any]] | None = None,
) -> bool:
    """Return True if user requested cancellation; clean up pending calls in session."""
    if not cancel_event or not cancel_event.is_set():
        return False

    if pending_tool_calls:
        for tc in pending_tool_calls:
            tc_id = tc.get("id") or "cancelled"
            tc_name = tc.get("function", {}).get("name", "unknown")
            session.add_tool_result(tc_id, tc_name, "Operation cancelled by user.")
    return True


async def handle_compaction(
    session: Any,
    cfg: Any,
    model: str,
    on_event: Callable[[Any], None] | None = None,
    agent_event_cls: Any = None,
) -> None:
    """Trigger session compaction if context approaches model token budget."""
    if not should_compact(session.get_api_messages(), model):
        return

    if on_event and agent_event_cls:
        on_event(agent_event_cls("compact", "Context approaching limit, compacting conversation..."))

    comp_res = await compact_session(session, model=model)
    if on_event and agent_event_cls:
        on_event(agent_event_cls("compact", {
            "success": comp_res.success,
            "old_tokens": comp_res.old_tokens,
            "new_tokens": comp_res.new_tokens,
            "display": f"Compacted: {comp_res.old_tokens:,} → {comp_res.new_tokens:,} tokens",
        }))
        on_event(agent_event_cls("token_usage", {
            "count": comp_res.new_tokens,
            "model": model,
            "display": format_usage(comp_res.new_tokens, model),
        }))
