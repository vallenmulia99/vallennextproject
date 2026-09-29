import base64
import os
from pathlib import Path
import asyncio
import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from vallen_cli.core.agent import run_agent, AgentEvent
from vallen_cli.core.skills import get_skills
from vallen_cli.core.file_tracker import get_file_tracker
from vallen_cli.providers.registry import get_registry
from vallen_cli.core.session import get_session_manager
from .diff_engine import compute_diff

router = APIRouter(prefix="/api/agent", tags=["agent"])

class AttachmentItem(BaseModel):
    name: str
    type: str = "file"
    data: str
    mime_type: Optional[str] = "application/octet-stream"
    size: Optional[int] = 0

class ChatRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    context: Optional[str] = None
    mode: Optional[str] = "auto"
    session_id: Optional[str] = None
    attachments: Optional[List[AttachmentItem]] = None
    autopilot: Optional[bool] = None

class InlineEditRequest(BaseModel):
    prompt: str
    selection: str = ""
    surrounding: str = ""
    language: str = "plaintext"
    path: str = ""
    model: Optional[str] = None

class DeleteSessionRequest(BaseModel):
    session_id: str

class ClearChatRequest(BaseModel):
    session_id: Optional[str] = None

class RevertRequest(BaseModel):
    path: str

class SwitchModelRequest(BaseModel):
    provider: Optional[str] = None
    model: str

def _extract_skills() -> List[Dict[str, Any]]:
    try:
        from .workspace_api import CURRENT_WORKSPACE
        active_dir = str(CURRENT_WORKSPACE)
    except Exception:
        active_dir = None
    skills_raw = get_skills(active_dir)
    if isinstance(skills_raw, dict):
        items = list(skills_raw.values())
    elif isinstance(skills_raw, (list, tuple)):
        items = list(skills_raw)
    else:
        items = []

    res = []
    for s in items:
        loc = getattr(s, "location", getattr(s, "path", ""))
        res.append({
            "name": getattr(s, "name", "Unnamed Skill"),
            "description": getattr(s, "description", ""),
            "path": str(loc)
        })
    return res

@router.get("/info")
async def get_agent_info() -> Dict[str, Any]:
    from vallen_cli.core.config import get_config
    cfg = get_config()
    cfg.load()
    registry = get_registry()
    registry.reload()
    provider = registry.active()
    models = []
    active_model = ""
    active_provider = ""

    if provider:
        active_model = provider.model or cfg.active_model
        active_provider = provider.name
        try:
            m_list = await provider.list_models()
            models = [{"id": m.id, "display_name": m.display_name, "provider": m.provider} for m in m_list]
        except Exception:
            models = [{"id": active_model, "display_name": active_model, "provider": provider.name}]

    return {
        "active_provider": active_provider,
        "active_model": active_model,
        "models": models,
        "skills": _extract_skills()
    }

@router.post("/set-model")
def set_model(req: SwitchModelRequest) -> Dict[str, Any]:
    from vallen_cli.core.config import get_config
    cfg = get_config()
    cfg.load()
    registry = get_registry()
    if req.provider:
        registry.set_active(req.provider)
        cfg.active_provider = req.provider
    provider = registry.active()
    if provider:
        provider.model = req.model
        cfg.active_model = req.model
        cfg.save()
        return {"status": "ok", "provider": provider.name, "model": provider.model}
    raise HTTPException(status_code=400, detail="No active provider found")

@router.get("/skills")
def list_skills() -> List[Dict[str, Any]]:
    return _extract_skills()

@router.get("/diff/all")
def get_all_diffs() -> List[Dict[str, Any]]:
    tracker = get_file_tracker()
    diffs = []
    for c in tracker.changes:
        diff_info = compute_diff(c.before or "", c.after or "", c.path)
        diffs.append({
            "path": c.path,
            "kind": c.kind,
            "additions": diff_info["additions"],
            "deletions": diff_info["deletions"],
            "original": c.before or "",
            "modified": c.after or ""
        })
    return diffs

@router.post("/diff/revert")
async def revert_diff(req: RevertRequest) -> Dict[str, Any]:
    tracker = get_file_tracker()
    ok, msg = await tracker.revert(req.path)
    return {"status": "ok" if ok else "error", "message": msg}


class ResumeSessionRequest(BaseModel):
    session_id: str

@router.post("/resume-session")
def resume_session_endpoint(req: ResumeSessionRequest) -> Dict[str, Any]:
    session = get_session_manager()
    ok = session.resume(req.session_id)
    return {"status": "ok" if ok else "error", "session_id": req.session_id}

@router.post("/clear-chat")
def clear_chat_endpoint(req: ClearChatRequest = ClearChatRequest()) -> Dict[str, Any]:
    from vallen_cli.core.database import get_session_db
    session = get_session_manager()
    db = get_session_db()
    sid = req.session_id or session.session_id
    if sid:
        db.clear_messages(sid)
        if session.session_id == sid:
            session.clear()
    else:
        session.clear()
    return {"status": "ok", "session_id": sid}

@router.post("/delete-session")
def delete_session_endpoint(req: DeleteSessionRequest) -> Dict[str, Any]:
    from vallen_cli.core.database import get_session_db
    db = get_session_db()
    session = get_session_manager()
    db.delete_session(req.session_id)
    if session.session_id == req.session_id:
        session.start_new()
    return {"status": "ok", "deleted": req.session_id, "active_session_id": session.session_id}

@router.post("/new-session")
def create_new_session() -> Dict[str, Any]:
    from .workspace_api import CURRENT_WORKSPACE
    from vallen_cli.core.workspace import get_workspace
    ws = get_workspace()
    ws.set_active_project(str(CURRENT_WORKSPACE))
    session = get_session_manager()
    new_id = session.start_new()
    return {"status": "ok", "session_id": new_id}

@router.get("/sessions")
def list_sessions() -> Dict[str, Any]:
    from .workspace_api import CURRENT_WORKSPACE
    from vallen_cli.core.database import get_session_db, _connect
    db = get_session_db()
    norm_project = str(CURRENT_WORKSPACE.resolve())
    raw_sessions = db.list_sessions()

    matching_sessions = []
    seen_ids = set()
    for s in raw_sessions:
        sp = s.get("project", "")
        try:
            resolved_sp = str(Path(sp).resolve()) if sp else ""
        except Exception:
            resolved_sp = sp

        if resolved_sp == norm_project or sp == str(CURRENT_WORKSPACE) or not sp:
            if s["id"] not in seen_ids:
                seen_ids.add(s["id"])
                matching_sessions.append(s)

    if not matching_sessions:
        matching_sessions = raw_sessions[:20]

    enriched = []
    for s in matching_sessions:
        with _connect() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (s["id"],)).fetchone()[0]
        enriched.append({
            "id": s["id"],
            "title": s.get("title") or "New Session",
            "updated_at": s.get("updated_at"),
            "model": s.get("model", ""),
            "message_count": cnt,
        })
    return {
        "project": norm_project,
        "project_name": Path(norm_project).name,
        "sessions": enriched,
    }

@router.get("/history")
def get_session_history(session_id: Optional[str] = None) -> Dict[str, Any]:
    """Restores conversation history for the current project path so nothing is lost on page reload."""
    from .workspace_api import CURRENT_WORKSPACE
    from vallen_cli.core.database import get_session_db
    session = get_session_manager()
    project_path = str(CURRENT_WORKSPACE.resolve())
    db = get_session_db()

    if session_id:
        resumed = session.resume(session_id)
        if not resumed:
            session.start_new()
    else:
        current_sess = db.get_session(session.session_id) if session.session_id else None
        if not current_sess or str(Path(current_sess.get("project", "")).resolve()) != project_path:
            last = db.last_session_for_project(project_path)
            if last:
                session.resume(last["id"])
            else:
                session.start_new()

    msgs = []
    for m in session._messages:
        if m.role == "system":
            continue
        msgs.append({
            "role": m.role,
            "content": m.content,
            "tool_calls": m.tool_calls,
            "tool_call_id": m.tool_call_id,
            "name": m.name,
        })
    return {
        "session_id": session.session_id,
        "title": session.title,
        "project": project_path,
        "project_name": Path(project_path).name,
        "messages": msgs,
    }

@router.post("/chat")
async def chat_sse(req: ChatRequest):
    if not req.prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    from .workspace_api import CURRENT_WORKSPACE
    from vallen_cli.core.workspace import get_workspace
    ws = get_workspace()
    active_path = str(CURRENT_WORKSPACE)
    if ws.active_project_path != active_path:
        ws.new_project(active_path)
        ws.set_active_project(active_path)
    try:
        os.chdir(active_path)
    except Exception:
        pass

    session = get_session_manager()
    if req.session_id and session.session_id != req.session_id:
        session.resume(req.session_id)

    # Set execution mode (plan vs build)
    if req.mode == "ask":
        session.mode = "plan"
    else:
        session.mode = "build"

    # Configure permission manager for IDE agent execution
    from vallen_cli.core.permission import get_permission_manager
    perm = get_permission_manager()
    if req.autopilot is not None:
        perm.allow_unsupervised = bool(req.autopilot)
    else:
        perm.allow_unsupervised = (req.mode in ("auto", "agent"))

    uploads_dir = Path(CURRENT_WORKSPACE) / ".vallen" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    image_parts = []
    file_notes = []

    if req.attachments:
        for att in req.attachments:
            safe_fname = Path(att.name).name
            save_path = uploads_dir / safe_fname
            is_image = att.type == "image" or (att.mime_type and att.mime_type.startswith("image/"))

            if is_image:
                try:
                    b64_data = att.data.split(",", 1)[1] if "," in att.data else att.data
                    raw_bytes = base64.b64decode(b64_data)
                    save_path.write_bytes(raw_bytes)
                except Exception as e:
                    print(f"Error saving image {att.name}: {e}")

                data_url = att.data if att.data.startswith("data:") else f"data:{att.mime_type or 'image/png'};base64,{att.data}"
                image_parts.append({
                    "type": "image_url",
                    "image_url": {"url": data_url}
                })
                file_notes.append(f"[Attached Image saved to: .vallen/uploads/{safe_fname}]")
            else:
                try:
                    if att.data.startswith("data:") and "," in att.data:
                        raw_bytes = base64.b64decode(att.data.split(",", 1)[1])
                        save_path.write_bytes(raw_bytes)
                        try:
                            text_content = raw_bytes.decode("utf-8")
                            file_notes.append(f"[Attached File: {safe_fname}]\n```\n{text_content[:4000]}\n```")
                        except Exception:
                            file_notes.append(f"[Attached Binary File saved to: .vallen/uploads/{safe_fname} ({len(raw_bytes):,} bytes)]")
                    else:
                        save_path.write_text(att.data, encoding="utf-8")
                        file_notes.append(f"[Attached File: {safe_fname}]\n```\n{att.data[:4000]}\n```")
                except Exception as e:
                    print(f"Error saving attachment {att.name}: {e}")

    text_prompt = req.prompt
    if file_notes:
        text_prompt = "\n\n".join(file_notes) + "\n\n" + text_prompt
    if req.context:
        text_prompt = f"{req.context}\n\nUser Request:\n{text_prompt}"

    if image_parts:
        full_prompt = [{"type": "text", "text": text_prompt}] + image_parts
    else:
        full_prompt = text_prompt

    queue: asyncio.Queue[Dict[str, Any] | None] = asyncio.Queue()
    tracker = get_file_tracker()
    initial_change_count = len(tracker.changes)

    def on_event(ev: AgentEvent):
        queue.put_nowait({"kind": ev.kind, "data": ev.data})

    is_autopilot = bool(req.autopilot) if req.autopilot is not None else (req.mode in ("auto", "agent"))
    effective_max_rounds = 100 if is_autopilot else 50

    async def run_task():
        try:
            res = await run_agent(
                full_prompt,
                on_event=on_event,
                model=req.model,
                max_tool_rounds=effective_max_rounds,
                autopilot=is_autopilot,
            )
            # Check if any new file changes occurred during this turn
            for change in tracker.changes[initial_change_count:]:
                diff_path = change.path
                try:
                    diff_path = str(Path(change.path).resolve().relative_to(CURRENT_WORKSPACE))
                except Exception:
                    pass
                diff_data = compute_diff(change.before or "", change.after or "", change.path)
                queue.put_nowait({
                    "kind": "diff_detected",
                    "data": {
                        "path": diff_path,
                        "raw_path": change.path,
                        "kind": change.kind,
                        "additions": diff_data["additions"],
                        "deletions": diff_data["deletions"],
                        "original": change.before or "",
                        "modified": change.after or ""
                    }
                })
            queue.put_nowait({"kind": "done", "data": res})
        except Exception as err:
            queue.put_nowait({"kind": "error", "data": str(err)})
        finally:
            queue.put_nowait(None)

    asyncio.create_task(run_task())

    async def event_generator():
        while True:
            ev = await queue.get()
            if ev is None:
                break
            yield f"data: {json.dumps(ev)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*"
        }
    )

@router.post("/inline-edit")
async def inline_edit_endpoint(req: InlineEditRequest) -> Dict[str, Any]:
    if not req.prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    from vallen_cli.providers.registry import get_registry
    from vallen_cli.core.config import get_config
    from vallen_cli.providers.base import Message

    cfg = get_config()
    registry = get_registry()
    provider = registry.active()
    if not provider:
        raise HTTPException(status_code=400, detail="No active LLM provider found")

    system_prompt = (
        "You are an expert AI code editor. Your task is to modify, fill, or generate code inline according to the user prompt.\n"
        "STRICT INSTRUCTIONS:\n"
        "1. Return ONLY the replacement code directly.\n"
        "2. Do NOT wrap output in markdown code blocks (no ```).\n"
        "3. Do NOT include conversational explanations or greetings.\n"
        "4. Preserve consistent indentation with surrounding code."
    )

    user_parts = []
    if req.path:
        user_parts.append(f"File: {req.path}")
    if req.language:
        user_parts.append(f"Language: {req.language}")
    if req.surrounding:
        user_parts.append(f"Surrounding Context:\n```\n{req.surrounding[:3000]}\n```")
    if req.selection:
        user_parts.append(f"Selected Code to Replace:\n```\n{req.selection}\n```")
    user_parts.append(f"Instruction:\n{req.prompt}\n\nStrictly return replacement code:")

    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content="\n\n".join(user_parts)),
    ]

    chosen_model = req.model or provider.model or cfg.active_model
    try:
        res = await provider.complete(messages=messages, model=chosen_model, temperature=0.2)
        code = res.content
        stripped = code.strip()
        if stripped.startswith("```"):
            first_line_end = stripped.find("\n")
            if first_line_end != -1:
                stripped = stripped[first_line_end + 1:]
            if stripped.endswith("```"):
                stripped = stripped[:-3].rstrip()
            code = stripped

        return {
            "status": "ok",
            "replacement": code,
            "model": chosen_model,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM generation failed: {e}")
