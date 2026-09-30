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
from .loop.turn_recovery import handle_length_truncation, should_retry_provider_error
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
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"MCP manager initialization failed: {exc}")
        if on_event:
            on_event(AgentEvent("info", f"MCP init notice: {exc}"))

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
    profile = "explore" if mode == "plan" else getattr(session, "tool_profile", "full")
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
    read_history_counts: dict[tuple[str, int, int], int] = {}

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

        # Accumulate input token usage for each conversation round
        input_tokens_total += token_count

        # ── Stream LLM response with bounded provider respawn ────────────────
        delta_buffer = ""
        reasoning_buffer = ""
        pending_tool_calls: list[dict[str, Any]] = []
        stream_succeeded = False
        provider_error: Exception | None = None

        for provider_attempt in range(MAX_PROVIDER_RETRIES + 1):
            attempt_delta = ""
            attempt_reasoning = ""
            attempt_pending_tool_calls: list[dict[str, Any]] = []
            prepared_tool_indices: set[int] = set()
            stream_finish_reason: str | None = None
            cancelled = False
            try:
                async with asyncio.timeout(PROVIDER_STREAM_TIMEOUT_SECONDS):
                    async for chunk in provider.stream_completion(
                        messages=messages,
                        model=effective_model or None,
                        temperature=agent_temperature,
                        max_tokens=cfg.max_tokens,
                        tools=tools if not is_last_round else None,
                    ):
                        if chunk.finish_reason:
                            stream_finish_reason = chunk.finish_reason

                        if cancel_event and cancel_event.is_set():
                            cancelled = True
                            if on_event:
                                on_event(AgentEvent("info", "Streaming cancelled by user"))
                            break

                        if chunk.finish_reason == "error":
                            err = RuntimeError(chunk.error or "Provider stream interrupted")
                            # Store retryable flag for outer exception handler
                            err.retryable = getattr(chunk, "retryable", True)  # type: ignore
                            raise err

                        if chunk.reasoning:
                            attempt_reasoning += chunk.reasoning
                            if on_event:
                                on_event(AgentEvent("reasoning", chunk.reasoning))

                        if chunk.content:
                            attempt_delta += chunk.content
                            if on_event:
                                on_event(AgentEvent("token", chunk.content))

                        if chunk.tool_calls:
                            for tc in chunk.tool_calls:
                                idx = tc.get("index")
                                if idx is None:
                                    idx = len(attempt_pending_tool_calls)
                                while len(attempt_pending_tool_calls) <= idx:
                                    attempt_pending_tool_calls.append(
                                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                                    )
                                entry = attempt_pending_tool_calls[idx]
                                func = tc.get("function", {})
                                if tc.get("id"):
                                    entry["id"] = tc["id"]
                                if func.get("name"):
                                    entry["function"]["name"] += func["name"]
                                if func.get("arguments"):
                                    entry["function"]["arguments"] += func["arguments"]

                                # Emit tool_prepare once per tool call as soon as name is received
                                t_name = entry["function"]["name"]
                                if t_name and idx not in prepared_tool_indices:
                                    prepared_tool_indices.add(idx)
                                    if on_event:
                                        on_event(AgentEvent("tool_prepare", {
                                            "index": idx,
                                            "name": t_name,
                                        }))

                        if chunk.finish_reason == "stop" or (chunk.finish_reason and not chunk.tool_calls):
                            stream_finish_reason = chunk.finish_reason
                            break

                if cancelled:
                    if attempt_delta:
                        session.add_assistant_message(attempt_delta)
                        full_response += attempt_delta
                    pending_tool_calls = []
                    delta_buffer = attempt_delta
                    break

                if not attempt_delta and not attempt_pending_tool_calls:
                    err = RuntimeError("Provider returned an empty response")
                    err.retryable = False  # Empty response likely means bad model/config, not transient
                    raise err

                # Commit successful attempt
                delta_buffer = attempt_delta
                reasoning_buffer = attempt_reasoning
                pending_tool_calls = attempt_pending_tool_calls
                full_response += attempt_delta
                output_tokens_total += max(1, len(attempt_delta) // 4)
                stream_succeeded = True
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                provider_error = exc
                should_retry, delay, classification = should_retry_provider_error(
                    exc, provider_attempt, MAX_PROVIDER_RETRIES
                )
                if not getattr(exc, "retryable", True) or not should_retry:
                    break
                if on_event:
                    on_event(AgentEvent("stream_reset", {}))
                    on_event(AgentEvent("provider_retry", {
                        "attempt": provider_attempt + 1,
                        "max_attempts": MAX_PROVIDER_RETRIES + 1,
                        "delay_seconds": delay,
                        "error": str(exc),
                        "kind": classification.kind,
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

            stop_turn_due_to_doom = False
            for tc_idx, tc in enumerate(pending_tool_calls):
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

                # Unwrap deferred tool_call to enforce permission, plan-mode, and profile checks
                if tool_name == "tool_call" and isinstance(args, dict) and "name" in args:
                    inner_name = args.get("name", "")
                    inner_args = args.get("arguments", {})
                    if inner_name == "tool_call":
                        output = "Error: Recursive tool_call invocation is not allowed."
                        session.add_tool_result(tool_call_id, tool_name, output)
                        if on_event:
                            on_event(AgentEvent("tool_result", {
                                "name": tool_name,
                                "output": output,
                                "success": False,
                            }))
                        messages = get_messages()
                        continue
                    tool_name = inner_name
                    args = inner_args if isinstance(inner_args, dict) else {}

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
                perm_path = args.get("filePath") or args.get("path") or args.get("file_path", "")
                patch_paths: list[str] = []
                if tool_name in ("shell", "run_shell", "bash"):
                    perm_path = args.get("command", "")
                elif tool_name == "apply_patch":
                    from ..tools.patch_tools import parse_vallen_patch
                    try:
                        hunks = parse_vallen_patch(args.get("patchText", ""))
                        for h in hunks:
                            if h.path:
                                patch_paths.append(h.path)
                            if h.move_to:
                                patch_paths.append(h.move_to)
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

                # ── Prepare preview if mutation tool ─────────────────────────
                perm_preview = ""
                if tool_name == "apply_patch":
                    perm_preview = args.get("patchText", "")[:1500]
                elif tool_name in ("edit", "edit_file"):
                    old_s = args.get("oldString") or args.get("old_text") or args.get("old_string", "")
                    new_s = args.get("newString") or args.get("new_text") or args.get("new_string", "")
                    if old_s or new_s:
                        perm_preview = f"- {old_s[:500]}\n+ {new_s[:500]}"
                elif tool_name in ("write", "write_file"):
                    perm_preview = args.get("content", "")[:1000]

                if tool_name == "apply_patch" and patch_paths:
                    allowed = True
                    for p_path in patch_paths:
                        p_req = PermRequest(
                            tool_name=tool_name,
                            description=f"Apply patch to {p_path}",
                            path=p_path,
                            preview=perm_preview,
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
                        preview=perm_preview,
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

                # ── Snapshot before write/edit/patch for UI diff & file tracker ─
                files_snapshot = await _snapshot_files_before(tool_name, args)
                primary_path = args.get("filePath") or args.get("path") or args.get("file_path", "")
                before_content = files_snapshot.get(primary_path) if primary_path else None

                # ── Execute tool with file lock if mutating a file ───────────
                # Check cancellation before executing each tool
                if cancel_event and cancel_event.is_set():
                    output = "Operation cancelled by user."
                    session.add_tool_result(tool_call_id, tool_name, output)
                    if on_event:
                        on_event(AgentEvent("tool_result", {"name": tool_name, "output": output, "success": False, "cancelled": True}))
                    messages = get_messages()
                    continue

                from ..tools.file_tools import _get_file_lock
                lock_path = perm_path if is_file_mutation and perm_path else None
                file_lock = _get_file_lock(lock_path) if lock_path else None

                try:
                    if file_lock:
                        async with file_lock:
                            result = await tool_registry.execute(tool_name, **args)
                    else:
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
                    # Reset repetitive read count if files are modified
                    read_history_counts.clear()

                output = format_tool_output(result)

                # Check repeated reads without changes
                if tool_name in ("read", "read_file") and result.success:
                    r_path = args.get("filePath") or args.get("path") or ""
                    r_offset = int(args.get("offset", 1))
                    r_limit = int(args.get("limit", 2000))
                    r_key = (r_path, r_offset, r_limit)
                    read_history_counts[r_key] = read_history_counts.get(r_key, 0) + 1
                    if read_history_counts[r_key] >= 3:
                        output += f"\n\n[Catatan]: Bagian ini ({r_path}, offset={r_offset}) sudah Anda baca {read_history_counts[r_key]} kali. Gunakan informasi yang sudah didapat atau gunakan `grep` untuk mencari bagian spesifik."
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

                ui_diff = ""
                if is_file_mutation and result.success and files_snapshot:
                    ui_diff = _build_unified_diff(files_snapshot, project_path)

                if on_event:
                    on_event(AgentEvent("tool_result", {
                        "name": tool_name,
                        "tool": tool_name,
                        "output": output,
                        "success": result.success,
                        "diff": ui_diff,
                    }))

                # Pass multimodal blocks if present (e.g. image read), else output string
                tool_msg_content = format_tool_content_for_session(result, output)
                session.add_tool_result(tool_call_id, tool_name, tool_msg_content)

                if doom_triggered:
                    stop_turn_due_to_doom = True
                    if on_event:
                        on_event(AgentEvent("error", f"Doom loop detected on {tool_name}"))
                    # Answer any remaining pending tool calls so session is not corrupted for LLM API
                    for rem_tc in pending_tool_calls[tc_idx + 1:]:
                        rem_id = rem_tc.get("id") or f"call_{int(time.time()*1000)}"
                        rem_name = rem_tc.get("function", {}).get("name", "unknown")
                        session.add_tool_result(rem_id, rem_name, "Operation skipped due to preceding doom loop error.")
                    break

            messages = get_messages()
            tool_round += 1
            if stop_turn_due_to_doom:
                break
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
            "model": effective_model or cfg.active_model,
            "display": format_usage(final_count, effective_model or cfg.active_model),
        }))
        on_event(AgentEvent("done", full_response))

    return full_response


# ── Helpers ──────────────────────────────────────────────────────────────────

def _describe_tool_call(tool_name: str, args: dict[str, Any]) -> str:
    path = args.get("filePath") or args.get("path") or args.get("file_path", "")
    if tool_name in ("read", "read_file"):
        offset = args.get("offset", 1)
        limit = args.get("limit", 2000)
        end = offset + limit - 1
        target = path or "file"
        return f"{target} (baris {offset}-{end})"
    if tool_name in ("grep", "search_files"):
        pat = args.get("pattern", "")
        target = path or args.get("include", "") or "."
        return f"'{pat}' di {target}"
    if tool_name in ("glob", "list_files"):
        pat = args.get("pattern", "")
        target = path or pat or "."
        return f"{target}"
    if tool_name in ("write", "write_file"):
        size = len(args.get("content", ""))
        return f"Write {size} bytes to {path or '?'}"
    if tool_name in ("edit", "edit_file"):
        return f"Edit {path or '?'}"
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


async def _snapshot_files_before(tool_name: str, args: dict[str, Any]) -> dict[str, str | None]:
    """Capture snapshot of files before write/edit/apply_patch for UI diff generation."""
    snapshots: dict[str, str | None] = {}
    paths: list[str] = []
    if tool_name in ("write", "write_file", "edit", "edit_file"):
        p_str = args.get("filePath") or args.get("path") or args.get("file_path", "")
        if p_str:
            paths.append(p_str)
    elif tool_name == "apply_patch":
        from ..tools.patch_tools import parse_vallen_patch
        try:
            hunks = parse_vallen_patch(args.get("patchText", ""))
            for h in hunks:
                if h.path:
                    paths.append(h.path)
                if h.move_to:
                    paths.append(h.move_to)
        except Exception:
            pass

    from ..core.workspace import resolve_workspace_path
    for p_str in paths:
        try:
            p = resolve_workspace_path(p_str)
            if p.exists() and p.is_file():
                content = await asyncio.to_thread(p.read_text, errors="replace")
                snapshots[str(p)] = content
            else:
                snapshots[str(p)] = None
        except Exception:
            snapshots[p_str] = None
    return snapshots


def _build_unified_diff(
    snapshots: dict[str, str | None],
    project_path: str = "",
    max_total_lines: int = 120,
) -> str:
    """Generate a clean unified diff preview with relative paths and line counts."""
    import difflib
    from pathlib import Path

    root = Path(project_path).resolve() if project_path else None
    diff_sections: list[str] = []
    total_lines = 0

    for path_str, before in snapshots.items():
        try:
            p = Path(path_str).resolve()
            after = p.read_text(errors="replace") if (p.exists() and p.is_file()) else None
            rel_path = str(p.relative_to(root)) if root else path_str
        except Exception:
            after = None
            rel_path = path_str

        if before == after:
            continue

        # Compute +A -B line changes
        before_lines = before.splitlines() if before is not None else []
        after_lines = after.splitlines() if after is not None else []
        diff_iter = list(difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            lineterm="",
            n=2,
        ))

        additions = sum(1 for l in diff_iter if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in diff_iter if l.startswith("-") and not l.startswith("---"))

        if before is None:
            status_desc = "file baru"
        elif after is None:
            status_desc = "dihapus"
        else:
            status_desc = "diubah"

        header = f"📝 {rel_path} ({status_desc}, +{additions} -{deletions})"
        diff_body: list[str] = []

        for line in diff_iter:
            if line.startswith("---") or line.startswith("+++"):
                continue
            diff_body.append(line)
            total_lines += 1
            if total_lines >= max_total_lines:
                diff_body.append("... (diff dipotong)")
                break

        section = header + ("\n" + "\n".join(diff_body) if diff_body else "")
        diff_sections.append(section)
        if total_lines >= max_total_lines:
            break

    return "\n\n".join(diff_sections)


def _record_change(tracker, tool_name: str, args: dict[str, Any], before: str | None, result) -> None:
    """Handle cache invalidation and tracking after a tool executes."""
    if not result.success:
        return
    path = args.get("filePath") or args.get("path", "")
    if not path:
        return
    try:
        from ..core.workspace import resolve_workspace_path
        p = resolve_workspace_path(path)
        if p.name == "SKILL.md" or p.name.endswith("SKILL.md"):
            invalidate_cache(str(p.parent))
    except (PermissionError, OSError, Exception):
        return

