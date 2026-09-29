"""VALLEN CLI — Auto compact & pruning memory management.

Mirrors OpenCode compaction.ts:
- PRUNE_MINIMUM: 20,000 tokens
- Tool output truncation/pruning to 2,000 chars before full summarization
- Structured LLM conversation compaction when overflow continues
"""

from __future__ import annotations

from typing import Any, Callable

from .token import estimate_messages, estimate, is_overflow, usable_context, PRUNE_MINIMUM
from .config import get_config
from .session import get_session_manager
from ..providers.base import Message
from ..providers.registry import get_registry

KEEP_RECENT = 4
TOOL_OUTPUT_MAX_CHARS = 2000
PRUNE_PROTECTED_TOOLS = {"skill", "list_skills"}
PRUNE_MARKER = "\n... [output pruned for context efficiency]"
PRUNE_STUB_TEMPLATE = "[output pruned: {tool_name}({args_summary}) — {original_size:,} chars. Reread with tool {tool_name} if needed.]"

COMPACT_SYSTEM_PROMPT = """\
You are a conversation summarizer. The user has been working with an AI coding agent.
Your job is to create a dense, structured summary of the conversation so far.

Use this exact structure:
## Goal
[What the user is trying to build or fix — one line]

## Progress
[What has been done: files created/modified, decisions made, key findings]

## Decisions
[Important decisions or trade-offs made during the session]

## Files
- Read: [list of files that were read, with brief note on why]
- Modified: [list of files that were edited/written, with what changed]

## Commands
[Build/test commands run and their results, if relevant]

## Next Steps
[What remains to be done, in priority order]

Be concise but complete. Write in third person. Use bullet points.
Do NOT include pleasantries. Output ONLY the summary.
"""


def create_prune_stub(message: Message, original_content: str) -> str:
    """Create an informative stub for pruned tool output."""
    tool_name = message.name or "unknown"
    args_summary = ""
    if isinstance(original_content, str):
        first_line = original_content.split("\n")[0][:100] if original_content else ""
        if "filePath" in first_line or "path" in first_line:
            args_summary = first_line
        elif original_content:
            args_summary = original_content[:50]
    return PRUNE_STUB_TEMPLATE.format(
        tool_name=tool_name,
        args_summary=args_summary[:80],
        original_size=len(original_content),
    )


def prune_tool_outputs(messages: list[Message]) -> int:
    """
    Stage 1: Prune older verbose tool outputs to 2,000 chars (OpenCode compaction.ts).
    Returns number of characters trimmed.
    """
    trimmed = 0
    # Keep the last 2 tool outputs untouched
    tool_indices = [i for i, m in enumerate(messages) if m.role == "tool"]
    exempt_indices = set(tool_indices[-2:]) if len(tool_indices) > 2 else set()

    for idx, msg in enumerate(messages):
        if msg.role == "tool" and idx not in exempt_indices:
            if msg.name in PRUNE_PROTECTED_TOOLS:
                continue
            content = msg.content
            if isinstance(content, list):
                # Only prune the text blocks inside a multimodal content list
                text_blocks = [
                    b for b in content
                    if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
                ]
                total_text_len = sum(len(b["text"]) for b in text_blocks)
                if total_text_len > TOOL_OUTPUT_MAX_CHARS:
                    excess = total_text_len - TOOL_OUTPUT_MAX_CHARS
                    removed = 0
                    for b in text_blocks:
                        if excess <= 0:
                            break
                        txt = b["text"]
                        if len(txt) > excess:
                            b["text"] = txt[:-excess]
                            removed += excess
                            excess = 0
                        else:
                            removed += len(txt)
                            excess -= len(txt)
                    trimmed += removed
                continue
            if content and len(content) > TOOL_OUTPUT_MAX_CHARS:
                before_len = len(content)
                msg.content = create_prune_stub(msg, content)
                trimmed += (before_len - len(msg.content))
    return trimmed


def prune_tool_outputs_to_budget(
    messages: list[Message],
    model_id: str,
    reserve_tokens: int = 8192,
    protected_recent: int = 2,
) -> int:
    """Prune oldest tool results until prompt fits its usable budget."""
    budget = max(1, usable_context(model_id))
    current = estimate_messages([m.to_api_dict() for m in messages])
    if current <= budget:
        return 0

    tool_indices = [i for i, m in enumerate(messages) if m.role == "tool"]
    protected = set(tool_indices[-protected_recent:])
    saved = 0
    for idx in tool_indices:
        if idx in protected:
            continue
        message = messages[idx]
        if message.name in PRUNE_PROTECTED_TOOLS:
            continue

        content = message.content
        if isinstance(content, list):
            # Prune text blocks inside multimodal content list; keep image blocks untouched
            text_blocks = [
                b for b in content
                if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
            ]
            if not text_blocks or sum(len(b["text"]) for b in text_blocks) <= 256:
                continue
            original_len = sum(len(b["text"]) for b in text_blocks)
            excess = original_len - 256
            removed = 0
            for b in text_blocks:
                if excess <= 0:
                    break
                txt = b["text"]
                if len(txt) > excess:
                    b["text"] = txt[:-excess]
                    removed += excess
                    excess = 0
                else:
                    removed += len(txt)
                    excess -= len(txt)
            saved += max(0, original_len - (original_len - removed))
            current = estimate_messages([m.to_api_dict() for m in messages])
            if current <= budget:
                break
            continue

        if len(content) <= 256:
            continue
        original = content
        message.content = create_prune_stub(message, original)
        saved += max(0, len(original) - len(message.content))
        current = estimate_messages([m.to_api_dict() for m in messages])
        if current <= budget:
            break
    return saved


async def prepare_context(messages: list[Message], model_id: str) -> tuple[int, int]:
    """Prune context before request; compact only when pruning cannot fit it."""
    saved = prune_tool_outputs_to_budget(messages, model_id)
    return saved, estimate_messages([m.to_api_dict() for m in messages])


async def estimate_session_tokens(messages: list[Message], model_id: str) -> int:
    api_msgs = [m.to_api_dict() for m in messages]
    return estimate_messages(api_msgs)


async def should_compact(messages: list[Message], model_id: str) -> bool:
    token_count = await estimate_session_tokens(messages, model_id)
    return is_overflow(token_count, model_id) and token_count > PRUNE_MINIMUM


async def compact_session(
    on_status: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    cfg = get_config()
    registry = get_registry()
    session = get_session_manager()

    provider = registry.active()
    if provider is None:
        return False, "No active provider."

    messages = session._messages
    if len(messages) < 4:
        return False, "Session too short to compact."

    model_id = cfg.active_model
    token_count_before = await estimate_session_tokens(session.get_api_messages(), model_id)

    # ── Stage 1: Pruning ────────────────────────────────────────────────
    chars_pruned = prune_tool_outputs(messages)
    token_count_after_prune = await estimate_session_tokens(session.get_api_messages(), model_id)

    if not is_overflow(token_count_after_prune, model_id):
        if on_status:
            on_status(f"  ✓ Pruned tool history ({chars_pruned:,} chars saved). Context within safe limit.")
        return True, "Tool history pruned."

    # ── Stage 2: Provider-native compaction when supported ───────────────
    native_messages = await _provider_compact_messages(provider, session.get_api_messages(), model_id)
    if native_messages is not None:
        session._messages = native_messages
        if session.session_id:
            session._db.clear_messages(session.session_id)
            for msg in native_messages:
                session._db.add_message(
                    session.session_id, msg.role, msg.content, tool_calls=msg.tool_calls,
                    tool_call_id=msg.tool_call_id, name=msg.name,
                )
        new_count = await estimate_session_tokens(session.get_api_messages(), model_id)
        if on_status:
            on_status(f"  ✓ Provider compacted: {token_count_before:,} → {new_count:,} tokens")
        return True, "Provider-native compaction complete."

    # ── Stage 2: Local summarization fallback ──────────────────────────
    if on_status:
        on_status(f"  Compacting session ({token_count_after_prune:,} tokens)…")

    conversation_parts: list[str] = []
    for msg in messages:
        if msg.role == "system":
            continue
        role_label = "User" if msg.role == "user" else "Assistant"
        text = msg.content or ""
        if isinstance(text, list):
            text = " ".join([b.get("text", "") for b in text if isinstance(b, dict) and b.get("type") == "text"]) or "[Image/Attachment]"
        if text.strip():
            if len(text) > 2000:
                text = text[:2000] + "\n[truncated]"
            conversation_parts.append(f"[{role_label}]: {text}")

    conversation = "\n\n".join(conversation_parts)

    summary_prompt = [
        Message(role="system", content=COMPACT_SYSTEM_PROMPT),
        Message(
            role="user",
            content=f"Please summarize this conversation:\n\n{conversation}",
        ),
    ]

    summary_text = ""
    try:
        async for chunk in provider.stream_completion(
            messages=summary_prompt,
            model=model_id,
            temperature=0.3,
            max_tokens=2048,
        ):
            if chunk.content:
                summary_text += chunk.content
            if chunk.finish_reason == "stop":
                break
    except Exception as e:
        return False, f"Compaction failed: {e}"

    if not summary_text.strip():
        return False, "Compaction produced empty summary."

    non_system = [m for m in session._messages if m.role != "system"]
    recent = non_system[-KEEP_RECENT:] if len(non_system) > KEEP_RECENT else []

    # Clean orphaned tool messages at start of recent (must have preceding assistant with tool_calls)
    while recent and recent[0].role == "tool":
        recent.pop(0)

    # If recent ends with assistant having tool_calls that are not answered in recent, strip those tool_calls
    if recent and recent[-1].role == "assistant" and recent[-1].tool_calls:
        recent[-1].tool_calls = None

    session._messages = []
    summary_msg = Message(
        role="user",
        content=f"[Conversation summary — context was compacted]\n\n{summary_text}",
    )
    ack_msg = Message(
        role="assistant",
        content="Understood. I have the summary of our previous work. Please continue.",
    )
    session._messages = [summary_msg, ack_msg] + recent

    if session.session_id:
        session._db.clear_messages(session.session_id)
        for msg in session._messages:
            session._db.add_message(
                session.session_id,
                msg.role,
                msg.content,
                tool_calls=msg.tool_calls,
                tool_call_id=msg.tool_call_id,
                name=msg.name,
            )

    new_count = await estimate_session_tokens(session.get_api_messages(), model_id)
    if on_status:
        on_status(
            f"  ✓ Compacted: {token_count_before:,} → {new_count:,} tokens\n"
            f"  Summary saved, {len(recent)} recent messages kept."
        )

    return True, summary_text


async def _provider_compact_messages(
    provider: Any, messages: list[Message], model_id: str
) -> list[Message] | None:
    compact = getattr(provider, "compact", None)
    if not callable(compact):
        return None
    try:
        result = compact(messages=messages, model=model_id)
        if hasattr(result, "__await__"):
            result = await result
        if isinstance(result, list) and all(isinstance(message, Message) for message in result):
            return result
    except (TypeError, NotImplementedError):
        return None
    except Exception:
        return None
    return None


def provider_compaction_available(provider: Any) -> bool:
    """Capability check for optional provider-native compaction."""
    return callable(getattr(provider, "compact", None))


async def compact_with_provider_or_local(provider: Any, on_status: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """Use provider compaction when implemented; otherwise use local compaction."""
    compact = getattr(provider, "compact", None)
    if callable(compact):
        try:
            result = await compact()
            return True, str(result or "Provider compaction complete.")
        except Exception as exc:
            if on_status:
                on_status(f"Provider compaction failed; using local fallback: {exc}")
    return await compact_session(on_status=on_status)
