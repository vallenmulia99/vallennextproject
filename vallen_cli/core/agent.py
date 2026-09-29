"""VALLEN CLI — Agent loop: LLM ↔ tools ↔ session.

Enhanced with OpenCode-inspired features:
  - Token usage tracking + context overflow detection
  - Auto compact when context approaches limit
  - Per-project agents.md system prompt injection
  - File change tracking
  - Permission confirmation before write/shell ops
"""

from __future__ import annotations
import asyncio
import time
import uuid
import re

import json
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Any

from .config import get_config
from .session import get_session_manager
from .workspace import get_workspace
from .agents_md import build_system_prompt
from .git_context import build_system_prompt_with_git
from .git_info import get_cached_git_info, build_git_context, invalidate_git_cache
from .skills import get_skills, invalidate_cache
from .snapshot import get_snapshot_manager
from .token import estimate_messages, format_usage, is_overflow
from .compact import should_compact, compact_session, prepare_context
from .file_tracker import get_file_tracker
from .telemetry import record_usage
from .permission import get_permission_manager, PermRequest, PermReply
from ..providers.registry import get_registry
from ..providers.base import Message, StreamChunk
from ..tools.registry import get_tool_registry, tool_names_for_profile
from ..tools.base import format_tool_output
from .loop.turn_tools import check_doom_loop, format_tool_content_for_session, truncate_large_output
from .loop.turn_recovery import handle_length_truncation
from .error_classifier import classify_error


@dataclass
class AgentEvent:
    """A single event emitted by the agent loop to the TUI."""
    kind: str   # "token"|"tool_start"|"tool_result"|"error"|"done"|"compact"|"token_usage"|"permission"
    data: Any = None


def effective_temperature(configured_temperature: float, model_id: str) -> float:
    """Use conservative sampling for models configured as GPT-6/Astra."""
    model_key = (model_id or "").lower()
    if "gpt-6" in model_key or "astra" in model_key:
        return min(configured_temperature, 0.3)
    return configured_temperature


async def run_agent(
    user_input: str,
    on_event: Callable[[AgentEvent], None] | None = None,
    max_tool_rounds: int = 50,
    model: str | None = None,
    autopilot: bool = False,
    cancel_event: asyncio.Event | None = None,
) -> str:
    """
    Main agent loop with streaming, tool calls, auto compact, and permissions.
    """
    cfg = get_config()
    registry = get_registry()
    tool_registry = get_tool_registry()
    session = get_session_manager()
    ws = get_workspace()
    project_path = ws.active_project_path
    tracker = get_file_tracker()
    perm = get_permission_manager()

    provider = registry.active()
    if provider is None:
        msg = "No active provider configured. Use /models or Ctrl+P to select one."
        if on_event:
            on_event(AgentEvent("error", msg))
        return msg

    # ── Initialize MCP servers if configured ──────────────────────────────
    try:
        from .mcp import get_mcp_manager
        await get_mcp_manager().initialize()
    except Exception:
        pass

    # ── Add user message ────────────────────────────────────────────────────
    session.add_user_message(user_input)

    # ── Build system prompt (OpenCode aligned) ───────────────────────────
    from .system_prompt import build_full_system_prompt
    effective_model = model or cfg.active_model
    # Astra/GPT-6 models are most reliable at deliberate, low-variance tool use.
    # Preserve a user's lower setting while preventing an old 0.7 default from
    # making edit and tool-selection behavior erratic.
    agent_temperature = effective_temperature(cfg.temperature, effective_model)
    is_default_prompt = (
        not cfg.system_prompt
        or "You are VALLEN CLI" in cfg.system_prompt
        or "You are VALLEN, an expert AI software engineering agent" in cfg.system_prompt
    )
    custom_prompt = None if is_default_prompt else cfg.system_prompt
    if session.cached_system_prompt is not None and not custom_prompt:
        effective_prompt = session.cached_system_prompt
    else:
        effective_prompt = await build_full_system_prompt(
            base_prompt=custom_prompt,
            project_path=project_path,
            model_id=effective_model,
            provider_name=cfg.active_provider,
            mode=getattr(session, "mode", "build"),
        )
        if not custom_prompt:
            session.cached_system_prompt = effective_prompt

    # ── Auto snapshot before first agent edit ────────────────────────────
    if project_path and session.session_id:
        snap_mgr = get_snapshot_manager(project_path)
        if snap_mgr.latest() is None or snap_mgr.latest().get("session_id") != session.session_id:
            await snap_mgr.take(session.session_id, f"Before: {str(user_input)[:60]}")

    def get_messages() -> list[Message]:
        msgs = session.get_api_messages()
        # Replace system message with agents.md-enhanced prompt
        if msgs and msgs[0].role == "system":
            msgs[0] = Message(role="system", content=effective_prompt)
        return msgs

    # ── Check if we need to auto compact before sending ────────────────────
    messages = get_messages()
    token_count = estimate_messages([m.to_api_dict() for m in messages])

    if on_event:
        on_event(AgentEvent("token_usage", {
            "count": token_count,
            "model": cfg.active_model,
            "display": format_usage(token_count, cfg.active_model),
        }))

    if await should_compact(messages, cfg.active_model):
        if on_event:
            on_event(AgentEvent("compact", {"status": "starting"}))

        def compact_status(msg: str) -> None:
            if on_event:
                on_event(AgentEvent("compact", {"status": msg}))

        success, summary = await compact_session(on_status=compact_status)
        if success and on_event:
            on_event(AgentEvent("compact", {"status": "done", "summary": summary}))
        messages = get_messages()

    mode = getattr(session, "mode", "build")
    profile = "explore" if mode == "plan" else "full"
    tools = tool_registry.schemas(tool_names_for_profile(profile))
    full_response = ""
    input_tokens_total = token_count
    output_tokens_total = 0
    tool_round = 0
    last_failure_sig: str | None = None
    failure_streak = 0
    verification_failures = 0
    baseline_verification: tuple[bool, str, str] | None = None
    MAX_VERIFICATION_RETRIES = 2
    MAX_PROVIDER_RETRIES = 2
    PROVIDER_STREAM_TIMEOUT_SECONDS = 180
    DOOM_LOOP_THRESHOLD = 3
    MAX_LENGTH_TRUNCATION_RETRIES = 2
    length_truncation_count = 0
    effective_max_rounds = max(max_tool_rounds, 100) if autopilot else max_tool_rounds
    pending_tool_calls: list[dict[str, Any]] = []

    def verification_signature(output: str) -> str:
        """Ignore volatile timing text when comparing two verification runs."""
        return re.sub(r"\bin\s+\d+(?:\.\d+)?s\b", "in <time>", output).strip()

    async def ensure_verification_baseline() -> tuple[bool, str, str]:
        """Capture project health before the first mutation in this agent run."""
        nonlocal baseline_verification
        if baseline_verification is None:
            result = await tool_registry.execute("verify", workdir=project_path)
            baseline_verification = (
                result.success,
                result.output if result.success else f"Error: {result.error}\n{result.output}".strip(),
                verification_signature(result.output if result.success else f"Error: {result.error}\n{result.output}".strip()),
            )
        return baseline_verification

    while tool_round <= effective_max_rounds:
        # Check cancellation before each round
        if cancel_event and cancel_event.is_set():
            if on_event:
                on_event(AgentEvent("info", "Agent cancelled by user"))
            # Answer any remaining pending tool calls so session stays valid
            for tc in pending_tool_calls:
                tc_id = tc.get("id") or f"call_{int(time.time()*1000)}"
                tc_name = tc.get("function", {}).get("name", "unknown")
                session.add_tool_result(tc_id, tc_name, "Operation cancelled by user.")
            break

        # Keep old tool output out of every subsequent request. This runs before
        # each model call, not only after the context has already overflowed.
        pruned_chars, token_count = await prepare_context(messages, effective_model or cfg.active_model)
        if pruned_chars and on_event:
            on_event(AgentEvent("compact", {"status": f"pruned context ({pruned_chars:,} chars saved)"}))
        if await should_compact(messages, effective_model or cfg.active_model):
            success, summary = await compact_session()
            if success:
                messages = get_messages()
        is_last_round = tool_round >= effective_max_rounds
        if is_last_round and on_event:
            on_event(AgentEvent("round_limit", {
                "round": tool_round,
                "max_rounds": effective_max_rounds,
                "autopilot": autopilot,
            }))

        # ── Stream LLM response with bounded provider respawn ────────────────
        delta_buffer = ""
        reasoning_buffer = ""
        pending_tool_calls: list[dict[str, Any]] = []
        stream_succeeded = False
        provider_error: Exception | None = None

        for provider_attempt in range(MAX_PROVIDER_RETRIES + 1):
            delta_buffer = ""
            reasoning_buffer = ""
            stream_finish_reason: str | None = None
            try:
                async with asyncio.timeout(PROVIDER_STREAM_TIMEOUT_SECONDS):
                    async for chunk in provider.stream_completion(
                        messages=messages,
                        model=effective_model or None,
                        temperature=agent_temperature,
                        max_tokens=cfg.max_tokens,
                        tools=tools if not is_last_round else None,
                    ):
                        if cancel_event and cancel_event.is_set():
                            if on_event:
                                on_event(AgentEvent("info", "Streaming cancelled by user"))
                            # Add what we have so far and break
                            if delta_buffer:
                                session.add_assistant_message(delta_buffer)
                            break
                        if chunk.finish_reason == "error":
                            err = RuntimeError(chunk.error or "Provider stream interrupted")
                            # Store retryable flag for outer exception handler
                            err.retryable = getattr(chunk, "retryable", True)  # type: ignore
                            raise err

                        if chunk.reasoning:
                            reasoning_buffer += chunk.reasoning
                            if on_event:
                                on_event(AgentEvent("reasoning", chunk.reasoning))

                        if chunk.content:
                            delta_buffer += chunk.content
                            full_response += chunk.content
                            output_tokens_total += max(1, len(chunk.content) // 4)
                            if on_event:
                                on_event(AgentEvent("token", chunk.content))

                        if chunk.tool_calls:
                            for tc in chunk.tool_calls:
                                idx = tc.get("index")
                                if idx is None:
                                    idx = len(pending_tool_calls)
                                while len(pending_tool_calls) <= idx:
                                    pending_tool_calls.append(
                                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                                    )
                                entry = pending_tool_calls[idx]
                                func = tc.get("function", {})
                                if tc.get("id"):
                                    entry["id"] = tc["id"]
                                if func.get("name"):
                                    entry["function"]["name"] += func["name"]
                                if func.get("arguments"):
                                    entry["function"]["arguments"] += func["arguments"]

                        if chunk.finish_reason == "stop" or (chunk.finish_reason and not chunk.tool_calls):
                            stream_finish_reason = chunk.finish_reason
                            break
                if not delta_buffer and not pending_tool_calls:
                    err = RuntimeError("Provider returned an empty response")
                    err.retryable = False  # Empty response likely means bad model/config, not transient
                    raise err
                stream_succeeded = True
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                provider_error = exc
                # Don't retry non-retryable errors (auth, bad request, etc.)
                if not getattr(exc, "retryable", True):
                    break
                if provider_attempt >= MAX_PROVIDER_RETRIES:
                    break
                delay = min(2 ** provider_attempt, 4)
                if on_event:
                    on_event(AgentEvent("provider_retry", {
                        "attempt": provider_attempt + 1,
                        "max_attempts": MAX_PROVIDER_RETRIES + 1,
                        "delay_seconds": delay,
                        "error": str(exc),
                    }))
                await asyncio.sleep(delay)

        if not stream_succeeded:
            message = f"Provider stream stopped after {MAX_PROVIDER_RETRIES + 1} attempts: {provider_error}"
            if on_event:
                on_event(AgentEvent("error", message))
            raise RuntimeError(message) from provider_error

        # ── Tool calls or final response ────────────────────────────────────
        if pending_tool_calls:
            session.add_assistant_message(delta_buffer, tool_calls=pending_tool_calls)
            messages = get_messages()

            for tc in pending_tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                raw_args = func.get("arguments", "{}")
                tool_call_id = tc.get("id") or f"call_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"

                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args_error = f"Error: Failed to parse tool arguments (invalid JSON): {raw_args[:200]}"
                    args = {}
                    # Send error to model instead of executing with empty args
                    session.add_tool_result(tool_call_id, tool_name, args_error)
                    if on_event:
                        on_event(AgentEvent("tool_result", {
                            "name": tool_name,
                            "output": args_error,
                            "success": False,
                            "parse_error": True,
                        }))
                    messages = get_messages()
                    continue

                # ── Plan Mode check ──────────────────────────────────────────
                if getattr(session, "mode", "build") == "plan" and tool_name in ("write", "write_file", "edit", "edit_file", "apply_patch"):
                    output = "Operation rejected: Plan mode is active. You are in read-only mode and cannot write or edit files. Use /build to switch back to execution mode."
                    if on_event:
                        on_event(AgentEvent("tool_result", {
                            "name": tool_name,
                            "output": output,
                            "success": False,
                            "rejected": True,
                        }))
                    session.add_tool_result(tool_call_id, tool_name, output)
                    messages = get_messages()
                    continue

                # ── Permission check ─────────────────────────────────────────
                perm_description = _describe_tool_call(tool_name, args)
                perm_path = args.get("filePath") or args.get("path", "")
                patch_paths: list[str] = []
                if tool_name in ("shell", "run_shell", "bash"):
                    perm_path = args.get("command", "")
                elif tool_name == "apply_patch":
                    from ..tools.patch_tools import parse_vallen_patch
                    try:
                        hunks = parse_vallen_patch(args.get("patchText", ""))
                        patch_paths = [h.path for h in hunks if h.path]
                        if patch_paths:
                            perm_path = ", ".join(patch_paths)
                    except Exception:
                        patch_paths = []

                if on_event:
                    on_event(AgentEvent("tool_start", {
                        "name": tool_name,
                        "tool": tool_name,
                        "args": args,
                        "description": perm_description,
                    }))

                if tool_name == "apply_patch" and patch_paths:
                    allowed = True
                    for p_path in patch_paths:
                        p_req = PermRequest(
                            tool_name=tool_name,
                            description=f"Apply patch to {p_path}",
                            path=p_path,
                        )
                        if not await perm.guard(p_req):
                            allowed = False
                            perm_description = f"Apply patch to {p_path}"
                            break
                else:
                    perm_request = PermRequest(
                        tool_name=tool_name,
                        description=perm_description,
                        path=perm_path,
                    )
                    allowed = await perm.guard(perm_request)
                if not allowed:
                    output = f"Operation rejected by user: {perm_description}"
                    if on_event:
                        on_event(AgentEvent("tool_result", {
                            "name": tool_name,
                            "output": output,
                            "success": False,
                            "rejected": True,
                        }))
                    session.add_tool_result(tool_call_id, tool_name, output)
                    messages = get_messages()
                    continue

                is_file_mutation = tool_name in ("write", "write_file", "edit", "edit_file", "apply_patch")
                if is_file_mutation and project_path:
                    await ensure_verification_baseline()

                # ── Snapshot before write/edit for file tracker ──────────────
                before_content = await _snapshot_before(tool_name, args)

                # ── Execute tool ─────────────────────────────────────────────
                # Check cancellation before executing each tool
                if cancel_event and cancel_event.is_set():
                    output = "Operation cancelled by user."
                    session.add_tool_result(tool_call_id, tool_name, output)
                    if on_event:
                        on_event(AgentEvent("tool_result", {"name": tool_name, "output": output, "success": False, "cancelled": True}))
                    messages = get_messages()
                    continue

                try:
                    result = await tool_registry.execute(tool_name, **args)
                except asyncio.CancelledError:
                    output = "Operation cancelled by parent agent."
                    session.add_tool_result(tool_call_id, tool_name, output)
                    if on_event:
                        on_event(AgentEvent("tool_result", {"name": tool_name, "output": output, "success": False, "cancelled": True}))
                    raise

                # ── Record file change ───────────────────────────────────────
                _record_change(tracker, tool_name, args, before_content, result)
                if result.success and tool_name in ("write", "write_file", "edit", "edit_file", "apply_patch", "shell", "run_shell"):
                    invalidate_git_cache(project_path)

                output = format_tool_output(result)
                cfg_verify_on_edit = cfg.get("verify", {}).get("on_edit", False) if isinstance(cfg.get("verify"), dict) else False
                if (
                    cfg_verify_on_edit
                    and result.success
                    and getattr(session, "mode", "build") == "build"
                    and tool_name in ("write", "write_file", "edit", "edit_file", "apply_patch")
                    and project_path
                ):
                    baseline_ok, _baseline_output, baseline_signature = await ensure_verification_baseline()
                    verify_result = await tool_registry.execute("verify", workdir=project_path)
                    # Treat verification timeout (exit code 124) as inconclusive, not a failure
                    verify_timed_out = (
                        isinstance(verify_result.error, str)
                        and "exit code 124" in verify_result.error
                    ) or (
                        verify_result.error
                        and hasattr(verify_result.error, 'returncode')
                        and verify_result.error.returncode == 124
                    )
                    if verify_timed_out:
                        verify_output = f"[Verification timed out — inconclusive] {verify_result.output or verify_result.error}"
                        output += f"\n\n[Automatic verification]{verify_output}"
                    else:
                        verify_output = verify_result.output if verify_result.success else f"Error: {verify_result.error}\n{verify_result.output}".strip()
                        if baseline_ok or verify_result.success:
                            output += f"\n\n[Automatic verification]\n{verify_output}"
                        elif verification_signature(verify_output) == baseline_signature:
                            output += "\n\n[Automatic verification]\nBaseline checks were already failing and are unchanged; do not treat them as caused by this edit."
                        else:
                            output += f"\n\n[Automatic verification: failures changed from baseline]\n{verify_output}"
                        if not verify_result.success and (baseline_ok or verification_signature(verify_output) != baseline_signature):
                            verification_failures += 1
                            if on_event:
                                on_event(AgentEvent("verification_retry", {
                                    "tool": tool_name,
                                    "attempt": verification_failures,
                                    "max_attempts": MAX_VERIFICATION_RETRIES,
                                    "diagnostics": [verify_output],
                                }))
                diagnostics = result.data.get("diagnostics", []) if isinstance(result.data, dict) else []
                if diagnostics:
                    verification_failures += 1
                    if on_event:
                        on_event(AgentEvent("verification_retry", {
                            "tool": tool_name,
                            "attempt": verification_failures,
                            "max_attempts": MAX_VERIFICATION_RETRIES,
                            "diagnostics": diagnostics,
                        }))
                    if verification_failures >= MAX_VERIFICATION_RETRIES:
                        output += f"\n\nVerification retry limit reached ({MAX_VERIFICATION_RETRIES}). Consider fixing these diagnostics before making further edits."
                elif result.success and tool_name in ("write", "write_file", "edit", "edit_file", "apply_patch"):
                    verification_failures = 0
                output = truncate_large_output(output, tool_name)

                # ── Doom loop detection ──────────────────────────────────────
                doom_triggered, last_failure_sig, failure_streak, doom_msg = check_doom_loop(
                    tool_name, raw_args, result.success, last_failure_sig, failure_streak, threshold=DOOM_LOOP_THRESHOLD
                )
                if doom_msg:
                    output += doom_msg

                if on_event:
                    on_event(AgentEvent("tool_result", {
                        "name": tool_name,
                        "tool": tool_name,
                        "output": output,
                        "success": result.success,
                    }))

                # Pass multimodal blocks if present (e.g. image read), else output string
                tool_msg_content = format_tool_content_for_session(result, output)
                session.add_tool_result(tool_call_id, tool_name, tool_msg_content)

                if doom_triggered:
                    if on_event:
                        on_event(AgentEvent("error", f"Doom loop detected on {tool_name}"))
                    # Answer any remaining pending tool calls so session is not corrupted for LLM API
                    curr_idx = pending_tool_calls.index(tc)
                    for rem_tc in pending_tool_calls[curr_idx + 1:]:
                        rem_id = rem_tc.get("id") or f"call_{int(time.time()*1000)}"
                        rem_name = rem_tc.get("function", {}).get("name", "unknown")
                        session.add_tool_result(rem_id, rem_name, "Operation skipped due to preceding doom loop error.")
                    break

            messages = get_messages()
            tool_round += 1
        else:
            if delta_buffer:
                session.add_assistant_message(delta_buffer)
            # Jika finish_reason == "length" tanpa tool call, jawaban terpotong
            if stream_finish_reason == "length" and length_truncation_count < MAX_LENGTH_TRUNCATION_RETRIES:
                length_truncation_count += 1
                if on_event:
                    on_event(AgentEvent("info", f"Balasan terpotong batas token (ke-{length_truncation_count}), meminta lanjutan..."))
                session.add_user_message("Balasanmu terpotong batas token. Lanjutkan tepat dari titik berhenti.")
                messages = get_messages()
                continue
            break

    # ── Final token usage update ────────────────────────────────────────────
    final_count = estimate_messages([m.to_api_dict() for m in get_messages()])
    record_usage(
        kind="agent",
        model=effective_model or cfg.active_model,
        input_tokens=input_tokens_total,
        output_tokens=output_tokens_total,
        rounds=tool_round,
    )
    if on_event:
        on_event(AgentEvent("token_usage", {
            "count": final_count,
            "model": cfg.active_model,
            "display": format_usage(final_count, cfg.active_model),
        }))
        on_event(AgentEvent("done", full_response))

    return full_response


# ── Helpers ──────────────────────────────────────────────────────────────────

def _describe_tool_call(tool_name: str, args: dict[str, Any]) -> str:
    path = args.get("filePath") or args.get("path", "?")
    if tool_name in ("write", "write_file"):
        size = len(args.get("content", ""))
        return f"Write {size} bytes to {path}"
    if tool_name in ("edit", "edit_file"):
        return f"Edit {path}"
    if tool_name in ("shell", "run_shell", "bash"):
        return f"Run: {args.get('command', '?')}"
    if tool_name == "apply_patch":
        from ..tools.patch_tools import parse_vallen_patch
        try:
            hunks = parse_vallen_patch(args.get("patchText", ""))
            paths = [h.path for h in hunks if h.path]
            if paths:
                return f"Apply patch to: {', '.join(paths)}"
        except Exception:
            pass
        return "Apply patch"
    if tool_name == "git_diff":
        return "Run git diff"
    return f"{tool_name}({', '.join(f'{k}={v!r}' for k, v in list(args.items())[:2])})"


async def _snapshot_before(tool_name: str, args: dict[str, Any]) -> str | None:
    """Read file content before a write/edit operation for diff tracking."""
    if tool_name not in ("write", "write_file", "edit", "edit_file"):
        return None
    path = args.get("filePath") or args.get("path", "")
    if not path:
        return None
    from ..core.workspace import resolve_workspace_path
    p = resolve_workspace_path(path)
    if p.exists() and p.is_file():
        try:
            return await asyncio.to_thread(p.read_text, errors="replace")
        except Exception:
            return None
    return None  # file doesn't exist yet = "created"


def _record_change(tracker, tool_name: str, args: dict[str, Any], before: str | None, result) -> None:
    """Handle cache invalidation and tracking after a tool executes."""
    if not result.success:
        return
    path = args.get("filePath") or args.get("path", "")
    if not path:
        return
    from ..core.workspace import resolve_workspace_path
    p = resolve_workspace_path(path)
    # File tools (write, edit, apply_patch) record changes directly to tracker
    # after formatting. Here we only invalidate skills cache if needed.
    if p.name == "SKILL.md" or p.name.endswith("SKILL.md"):
        invalidate_cache(str(p.parent))

