"""VALLEN CLI — Subagent Task tool.

Mirrors OpenCode task.ts:
Allows the primary agent to delegate focused research or exploration tasks
to specialized subagents ('explore', 'general') with isolated contexts.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextvars import ContextVar
from typing import Any
from pathlib import Path

from .base import BaseTool, ToolResult, format_tool_output
from ..providers.base import Message
from ..providers.registry import get_registry
from ..core.config import get_config
from ..core.workspace import get_workspace
from ..core.task_registry import record_task, recover_running_tasks, get_task, save_task_messages, load_task_messages
from ..core.worktree import create_worktree, remove_worktree, collect_diff, apply_diff, prune_orphan_worktrees
from ..core.telemetry import record_usage
from ..core.workspace import workspace_scope
from ..core.skills import get_skills
from ..core.agent_config import load_agent_autoload_skills
from ..core.compact import prune_tool_outputs_to_budget


EXPLORE_PROMPT = """You are an exploration subagent. Your job is to explore the codebase quickly and accurately.
Find relevant files, examine code structures, and answer the parent agent's question.
Tools available: `read`, `glob`, `grep`.
Be concise, factual, and cite file paths with line numbers (path:line).
Output ONLY the requested summary without unnecessary chit-chat.
"""

GENERAL_PROMPT = """You are a focused research subagent. Complete the requested research or sub-problem.
Tools available: `read`, `glob`, `grep`, `webfetch`.
Provide a clear, structured summary of your findings to the parent agent.
"""

ARCHITECT_PROMPT = """You are a software architecture subagent.
Your goal is to inspect the codebase and design clean, maintainable technical blueprints.
Trace data flows, identify modular boundaries, and plan step-by-step implementations.
Be structured, precise, and practical. Cite specific existing patterns and files.
"""

REVIEWER_PROMPT = """You are a code review and security auditing subagent.
Examine code for bugs, logic errors, security vulnerabilities, edge cases, and performance traps.
Prioritize findings from high to low severity. Provide actionable, surgical recommendations.
"""

SIMPLIFIER_PROMPT = """You are a code simplification subagent.
Analyze code to eliminate unnecessary layers, dead logic, and over-engineering while preserving 100% of behavior.
Be concise and show before/after simplification logic clearly.
"""

IMPLEMENTER_PROMPT = """You are an implementation subagent working in an isolated Git worktree.
Inspect the relevant code, make the requested focused changes with read, edit, write, or apply_patch, then run verify.
Do not modify unrelated files. Report the files changed, verification result, and any blocker to the parent agent.
"""

# Subagent session memory cache: task_id -> list[Message]
_subagent_sessions: dict[str, list[Message]] = {}
_subagent_outputs: dict[str, str] = {}
_subagent_status: dict[str, dict[str, Any]] = {}
SUBAGENT_TOOL_TIMEOUT_SECONDS = 45
MAX_SUBAGENT_TOOL_OUTPUT_CHARS = 6000

MAX_PARALLEL_SUBAGENT_TOOLS = 4
_subagent_tool_semaphore = asyncio.Semaphore(MAX_PARALLEL_SUBAGENT_TOOLS)
MAX_SUBAGENT_DEPTH = 2
_subagent_depth: ContextVar[int] = ContextVar("subagent_depth", default=0)
_active_subagent_tasks: dict[str, asyncio.Task[Any]] = {}


def get_task_result(task_id: str) -> str | None:
    return _subagent_outputs.get(task_id)


def cancel_active_task(task_id: str) -> bool:
    task = _active_subagent_tasks.get(task_id)
    if not task or task.done():
        return False
    task.cancel()
    return True


def mark_task_failed(task_id: str, error: str) -> None:
    _subagent_status[task_id] = {"task_id": task_id, "status": "failed", "error": error}
    record_task(task_id, status="failed", error=error)


class TaskTool(BaseTool):
    name = "task"
    description = "Launch a new agent to handle complex, multistep tasks autonomously.\n\nWhen using the Task tool, you must specify a subagent_type parameter to select which agent type to use.\n\nWhen NOT to use the Task tool:\n- If you want to read a specific file path, use the Read or Glob tool instead of the Task tool, to find the match more quickly\n- If you are searching for a specific class definition like \"class Foo\", use the Grep tool instead, to find the match more quickly\n- If you are searching for code within a specific file or set of 2-3 files, use the Read tool instead of the Task tool, to find the match more quickly\n- If no available agent is a good fit for the task, use other tools directly\n\n\nUsage notes:\n1. Launch multiple agents concurrently whenever possible, to maximize performance; to do that, use a single message with multiple tool uses\n2. Once you have delegated work to an agent, do not duplicate that work yourself. Continue with non-overlapping tasks, or wait for the result. For background tasks, you will be notified automatically when the result is ready.\n3. When the agent is done, it will return a single message back to you. The result returned by the agent is not visible to the user. To show the user the result, you should send a text message back to the user with a concise summary of the result. The output includes a task_id you can reuse later to continue the same subagent session.\n4. Each agent invocation starts with a fresh context unless you provide task_id to resume the same subagent session (which continues with its previous messages and tool outputs). When starting fresh, your prompt should contain a highly detailed task description for the agent to perform autonomously and you should specify exactly what information the agent should return back to you in its final and only message to you.\n5. The agent's outputs should generally be trusted\n6. Clearly tell the agent whether you expect it to write code or just to do research (search, file reads, web fetches, etc.), since it is not aware of the user's intent. Tell it how to verify its work if possible (e.g., relevant test commands).\n7. If the agent description mentions that it should be used proactively, then you should try your best to use it without the user having to ask for it first. Use your judgement."
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "A short (3-5 words) description of the task",
            },
            "prompt": {
                "type": "string",
                "description": "The detailed task for the subagent to perform",
            },
            "subagent_type": {
                "type": "string",
                "enum": ["explore", "architect", "reviewer", "simplifier", "implementer", "general"],
                "description": "The type of specialized agent to use; implementer edits only in an isolated worktree.",
            },
            "task_id": {
                "type": "string",
                "description": "Optional prior task_id to continue a previous subagent conversation",
            },
            "isolated": {
                "type": "boolean",
                "description": "Run subagent tools in a temporary Git worktree (default false).",
            },
            "merge": {
                "type": "boolean",
                "description": "Apply isolated worktree diff to parent after completion (default false).",
            },
        },
        "required": ["description", "prompt", "subagent_type"],
    }

    async def execute(
        self,
        description: str,
        prompt: str,
        subagent_type: str = "explore",
        task_id: str = "",
        isolated: bool = False,
        merge: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        depth = _subagent_depth.get()
        if depth >= MAX_SUBAGENT_DEPTH:
            return ToolResult(success=False, output="", error=f"Nested subagent depth limit reached ({MAX_SUBAGENT_DEPTH})")
        depth_token = _subagent_depth.set(depth + 1)
        try:
            registry = get_registry()
            provider = registry.active()
            if not provider:
                return ToolResult(success=False, output="", error="No active provider for subagent")

            from .registry import get_tool_registry
            tool_reg = get_tool_registry()
            parent_root = get_workspace().active_project_path
            isolated_path: Path | None = None
            isolated_branch = ""
            diff_stat = ""
            diff_patch = ""
            # Implementers always work in a disposable worktree.  Their output
            # can be reviewed and merged by the parent without touching it.
            if subagent_type == "implementer":
                if not parent_root:
                    return ToolResult(success=False, output="", error="Implementer tasks require an active project workspace")
                isolated = True
            if isolated and parent_root:
                try:
                    await prune_orphan_worktrees(parent_root)
                    isolated_path, isolated_branch = await create_worktree(parent_root)
                except (OSError, RuntimeError) as exc:
                    return ToolResult(success=False, output="", error=f"Could not create isolated worktree: {exc}")

            # Tools and prompts for specialized subagents
            if subagent_type == "explore":
                allowed_names = {"read", "glob", "grep"}
                system_inst = EXPLORE_PROMPT
            elif subagent_type == "architect":
                allowed_names = {"read", "glob", "grep"}
                system_inst = ARCHITECT_PROMPT
            elif subagent_type == "reviewer":
                allowed_names = {"read", "glob", "grep"}
                system_inst = REVIEWER_PROMPT
            elif subagent_type == "simplifier":
                allowed_names = {"read", "glob", "grep"}
                system_inst = SIMPLIFIER_PROMPT
            elif subagent_type == "implementer":
                allowed_names = {"read", "glob", "grep", "edit", "write", "apply_patch", "verify"}
                system_inst = IMPLEMENTER_PROMPT
            else:
                allowed_names = {"read", "glob", "grep", "webfetch", "task"}
                system_inst = GENERAL_PROMPT + "\nYou may delegate one focused child task when useful."

            sub_tools = tool_reg.schemas(allowed_names)

            recover_running_tasks()
            active_task_id = task_id or f"task_{uuid.uuid4().hex[:8]}"
            current_async_task = asyncio.current_task()
            if current_async_task:
                _active_subagent_tasks[active_task_id] = current_async_task
            if task_id and get_task(task_id) and get_task(task_id).get("status") == "interrupted":
                _subagent_status[task_id] = {"task_id": task_id, "status": "resuming"}
            record_task(
                active_task_id,
                status="running",
                subagent_type=subagent_type,
                description=description,
                artifact=f".vallen/tasks/{active_task_id}.md",
            )

            if active_task_id in _subagent_sessions:
                messages = _subagent_sessions[active_task_id]
                messages.append(Message(role="user", content=prompt))
            else:
                persisted = load_task_messages(active_task_id) if task_id else None
                if persisted:
                    messages = [Message(**item) for item in persisted]
                    messages.append(Message(role="user", content=prompt))
                else:
                    messages = [Message(role="system", content=system_inst)]
                    project_skills = get_skills(parent_root)
                    for skill_name in load_agent_autoload_skills(parent_root, subagent_type):
                        skill = project_skills.get(skill_name)
                        if skill:
                            messages.append(Message(
                                role="user",
                                content=(
                                    f"[Autoloaded skill: {skill.name}]\n"
                                    f"{skill.content.strip()[:12000]}\n"
                                    f"[End skill: {skill.name}]"
                                ),
                            ))
                    messages.append(Message(role="user", content=prompt))
                _subagent_sessions[active_task_id] = messages
            save_task_messages(active_task_id, [message.to_api_dict() for message in messages])

            cfg = get_config()
            # Smart Dual-Model Routing:
            # - explore / general / simplifier -> fast subagent model (low latency & token cost)
            # - architect / reviewer -> main model (deep reasoning & security analysis)
            if subagent_type in ("architect", "reviewer"):
                subagent_model = cfg.active_model or cfg.active_subagent_model or None
            else:
                subagent_model = cfg.active_subagent_model or cfg.active_model or None
            rounds = 0
            max_sub_rounds = 5
            final_text = ""

            while rounds < max_sub_rounds:
                current_task = get_task(active_task_id)
                if current_task and current_task.get("status") == "cancelled":
                    # Cleanup worktree before exit
                    if isolated_path and parent_root:
                        try:
                            await remove_worktree(parent_root, isolated_path, isolated_branch)
                        except Exception:
                            pass
                    _subagent_status[active_task_id] = {"task_id": active_task_id, "status": "cancelled"}
                    _active_subagent_tasks.pop(active_task_id, None)
                    return ToolResult(success=False, output="", error="Subagent task cancelled")
                rounds += 1
                prune_tool_outputs_to_budget(messages, subagent_model or cfg.active_model, protected_recent=2)
                delta_buffer = ""
                tool_calls: list[dict[str, Any]] = []
                is_last_sub_round = rounds >= max_sub_rounds

                async for chunk in provider.stream_completion(
                    messages=messages,
                    model=subagent_model,
                    temperature=0.3,
                    max_tokens=4096,
                    tools=sub_tools if not is_last_sub_round else None,
                ):
                    if chunk.finish_reason == "error":
                        error_msg = f"Provider error during subagent execution: {chunk.error}"
                        return ToolResult(success=False, output="", error=error_msg)

                    if chunk.content:
                        delta_buffer += chunk.content

                    if chunk.tool_calls:
                        for tc in chunk.tool_calls:
                            idx = tc.get("index")
                            if idx is None:
                                idx = len(tool_calls)
                            while len(tool_calls) <= idx:
                                tool_calls.append(
                                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                                )
                            entry = tool_calls[idx]
                            func = tc.get("function", {})
                            if tc.get("id"):
                                entry["id"] = tc["id"]
                            if func.get("name"):
                                entry["function"]["name"] += func["name"]
                            if func.get("arguments"):
                                entry["function"]["arguments"] += func["arguments"]

                    if chunk.finish_reason == "stop" or (chunk.finish_reason and not chunk.tool_calls):
                        break

                if tool_calls:
                    messages.append(Message(role="assistant", content=delta_buffer, tool_calls=tool_calls))
                    save_task_messages(active_task_id, [message.to_api_dict() for message in messages])

                    async def execute_subagent_tool(tc: dict[str, Any]) -> tuple[str, str, str]:
                        import time
                        func = tc.get("function", {})
                        t_name = func.get("name", "")
                        raw_args = func.get("arguments", "{}")
                        t_id = tc.get("id") or f"call_sub_{int(time.time()*1000)}"

                        try:
                            args = json.loads(raw_args) if raw_args else {}
                        except json.JSONDecodeError:
                            error_msg = f"Error: Failed to parse tool arguments (invalid JSON): {raw_args[:200]}"
                            return t_id, t_name, error_msg
                        if not isinstance(args, dict):
                            error_msg = f"Error: Tool arguments must be a JSON object, got {type(args).__name__}"
                            return t_id, t_name, error_msg

                        # Resolve aliases (e.g. read_file -> read, write_file -> write)
                        from .registry import get_tool_registry
                        reg_check = get_tool_registry()
                        actual_tool = reg_check.get(t_name)
                        primary_name = actual_tool.name if actual_tool else t_name

                        if allowed_names is not None and primary_name not in allowed_names:
                            return t_id, t_name, f"Error: Tool '{t_name}' is not allowed for subagent type '{subagent_type}'."

                        if primary_name == "tool_call":
                            inner_target = args.get("name", "") if isinstance(args, dict) else ""
                            if allowed_names is not None and inner_target not in allowed_names:
                                return t_id, t_name, f"Error: Tool '{inner_target}' is not allowed via tool_call."
                        # Permission guard for mutating tools when not isolated
                        if not isolated_path and primary_name in ("write", "write_file", "edit", "edit_file", "apply_patch", "shell", "run_shell"):
                            from ..core.permission import get_permission_manager, PermRequest
                            pm = get_permission_manager()
                            req = PermRequest(tool_name=primary_name, description=f"Subagent '{subagent_type}' execution of {primary_name}")
                            allowed = await pm.guard(req)
                            if not allowed:
                                return t_id, t_name, f"Error: Permission denied by user for {primary_name} in subagent."

                        try:
                            async def run_tool():
                                if isolated_path:
                                    with workspace_scope(str(isolated_path)):
                                        return await tool_reg.execute(t_name, **args)
                                return await tool_reg.execute(t_name, **args)
                            async with _subagent_tool_semaphore:
                                res = await asyncio.wait_for(run_tool(), timeout=SUBAGENT_TOOL_TIMEOUT_SECONDS)
                        except asyncio.TimeoutError:
                            return t_id, t_name, f"Error: tool timed out after {SUBAGENT_TOOL_TIMEOUT_SECONDS}s"
                        output = format_tool_output(res)
                        if len(output) > MAX_SUBAGENT_TOOL_OUTPUT_CHARS:
                            output = output[:MAX_SUBAGENT_TOOL_OUTPUT_CHARS] + "\n... [subagent tool output truncated]"
                        return t_id, t_name, output

                    unique_calls: list[dict[str, Any]] = []
                    seen_calls: set[tuple[str, str]] = set()
                    for tool_call in tool_calls:
                        func = tool_call.get("function", {})
                        signature = (func.get("name", ""), func.get("arguments", ""))
                        if signature not in seen_calls:
                            seen_calls.add(signature)
                            unique_calls.append(tool_call)
                    results = await asyncio.gather(*(execute_subagent_tool(tc) for tc in unique_calls))

                    # Build map from signature -> result (for deduplication)
                    result_by_sig: dict[tuple[str, str], tuple[str, str, str]] = {}
                    for unique_tc, (t_id, t_name, out) in zip(unique_calls, results):
                        func = unique_tc.get("function", {})
                        sig = (func.get("name", ""), func.get("arguments", ""))
                        result_by_sig[sig] = (t_id, t_name, out)

                    # Create tool messages for ALL tool calls (including duplicates)
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        sig = (func.get("name", ""), func.get("arguments", ""))
                        if sig in result_by_sig:
                            _, t_name, out = result_by_sig[sig]
                            t_id = tc.get("id", "")
                            messages.append(Message(role="tool", content=out, tool_call_id=t_id, name=t_name))

                    save_task_messages(active_task_id, [message.to_api_dict() for message in messages])
                else:
                    if delta_buffer:
                        messages.append(Message(role="assistant", content=delta_buffer))
                        final_text = delta_buffer
                    save_task_messages(active_task_id, [message.to_api_dict() for message in messages])
                    break

            result_text = final_text.strip() or "(no output)"
            _subagent_outputs[active_task_id] = result_text
            record_usage(
                kind="subagent",
                model=subagent_model or cfg.active_model,
                input_tokens=sum(max(1, len(message.content) // 4) for message in messages),
                output_tokens=max(1, len(result_text) // 4),
                rounds=rounds,
            )
            _subagent_status[active_task_id] = {
                "task_id": active_task_id,
                "status": "completed",
                "subagent_type": subagent_type,
                "description": description,
                "rounds": rounds,
            }
            record_task(
                active_task_id,
                status="completed",
                subagent_type=subagent_type,
                description=description,
                rounds=rounds,
                artifact=f".vallen/tasks/{active_task_id}.md",
            )
            if isolated_path and parent_root:
                diff_stat, diff_patch = await collect_diff(parent_root, isolated_path)
                if merge and diff_patch:
                    merged, merge_message = await apply_diff(parent_root, diff_patch)
                    if not merged:
                        result_text += f"\n\nMerge failed: {merge_message}"
                    else:
                        result_text += f"\n\n{merge_message}"
                await remove_worktree(parent_root, isolated_path, isolated_branch)

            artifact_dir = Path(get_workspace().active_project_path or ".") / ".vallen" / "tasks"
            try:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / f"{active_task_id}.md").write_text(
                    f"# Task {active_task_id}\n\n"
                    f"- Status: completed\n- Agent: {subagent_type}\n"
                    f"- Description: {description}\n- Rounds: {rounds}\n\n"
                    f"{result_text}\n"
                    + (f"\n## Worktree diff\n\n```text\n{diff_stat}```\n" if diff_stat else "")
                )
            except OSError:
                pass
            preview = result_text[:5000]
            if len(result_text) > len(preview):
                preview += f"\n... [full result retained for task_id {active_task_id}]"
            output = (
                f"[Subagent '{subagent_type}' completed task '{description}']\n"
                f"task_id: {active_task_id}\n"
                f"rounds: {rounds}\n\n{preview}"
            )
            _active_subagent_tasks.pop(active_task_id, None)
            return ToolResult(
                success=True,
                output=output,
                data={
                    "task_id": active_task_id,
                    "subagent_type": subagent_type,
                    "status": "completed",
                    "artifact": f".vallen/tasks/{active_task_id}.md",
                    "isolated": isolated_path is not None,
                    "worktree": str(isolated_path) if isolated_path else None,
                    "diff_stat": diff_stat,
                    "merged": bool(merge and isolated_path and diff_patch),
                },
            )
        finally:
            _subagent_depth.reset(depth_token)
