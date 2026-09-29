import sys
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from vallen_cli.core.workspace import get_workspace

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

# ── Dynamic Workspace Manager (Single Source of Truth) ─────────────────────
def get_current_workspace() -> Path:
    """Return the active workspace path, synchronized with WorkspaceManager and projects.json."""
    try:
        from vallen_cli.core.workspace import get_workspace
        ws = get_workspace()
        if ws.active_project_path:
            p = Path(ws.active_project_path).resolve()
            if p.exists() and p.is_dir() and not str(p).startswith("/tmp/pytest"):
                return p
    except Exception:
        pass

    try:
        from vallen_cli.core.config import get_projects_db
        pdb = get_projects_db()
        act = pdb.get_active()
        if act and act.get("path"):
            p = Path(act["path"]).resolve()
            if p.exists() and p.is_dir() and not str(p).startswith("/tmp/pytest"):
                return p
    except Exception:
        pass

    return Path(os.getcwd()).resolve()


def set_current_workspace(target_path: str | Path) -> Path:
    """Persistently update the active workspace across CLI, IDE, and agent runtime."""
    p = Path(os.path.expanduser(str(target_path))).resolve()
    from vallen_cli.core.workspace import get_workspace
    from vallen_cli.core.config import get_projects_db
    ws = get_workspace()
    pdb = get_projects_db()
    pdb.add_project(str(p))
    pdb.set_active(str(p))
    ws.new_project(str(p))
    ws.set_active_project(str(p))
    try:
        os.chdir(str(p))
    except Exception:
        pass
    return p


class CurrentWorkspaceProxy:
    """Dynamic proxy so any code referencing CURRENT_WORKSPACE always accesses the live active path."""
    def __str__(self) -> str:
        return str(get_current_workspace())
    def __repr__(self) -> str:
        return repr(get_current_workspace())
    def __fspath__(self) -> str:
        return str(get_current_workspace())
    def __getattr__(self, name: str) -> Any:
        return getattr(get_current_workspace(), name)
    def __truediv__(self, other: Any) -> Path:
        return get_current_workspace() / other
    def __rtruediv__(self, other: Any) -> Path:
        return other / get_current_workspace()


CURRENT_WORKSPACE = CurrentWorkspaceProxy()


class OpenProjectRequest(BaseModel):
    path: str

class SaveFileRequest(BaseModel):
    path: str
    content: str

class CreateItemRequest(BaseModel):
    path: str
    type: str = "file"

class DeleteItemRequest(BaseModel):
    path: str

class RenameItemRequest(BaseModel):
    old_path: str
    new_path: str

class SearchRequest(BaseModel):
    query: str
    case_sensitive: bool = False

class CommitRequest(BaseModel):
    message: str

class RemoveRecentProjectRequest(BaseModel):
    path: str


def safe_resolve(path_str: str) -> Path:
    curr = get_current_workspace()
    p = Path(path_str)
    if p.is_absolute():
        resolved = p.resolve()
        try:
            resolved.relative_to(curr)
            return resolved
        except ValueError:
            raise HTTPException(status_code=403, detail="Akses di luar workspace tidak diizinkan")
    target = (curr / path_str.lstrip("/")).resolve()
    try:
        target.relative_to(curr)
    except ValueError:
        raise HTTPException(status_code=403, detail="Akses di luar workspace tidak diizinkan")
    return target


@router.get("/current")
def get_current_workspace_endpoint() -> Dict[str, str]:
    curr = get_current_workspace()
    return {
        "path": str(curr),
        "name": curr.name
    }


@router.post("/open-project")
def open_project(req: OpenProjectRequest) -> Dict[str, Any]:
    target = Path(os.path.expanduser(req.path)).resolve()
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail=f"Direktori tidak ditemukan: {req.path}")

    curr = set_current_workspace(target)
    try:
        from vallen_cli.core.session import get_session_manager
        from vallen_cli.core.database import get_session_db
        sm = get_session_manager()
        db = get_session_db()
        last = db.last_session_for_project(str(curr))
        if last:
            sm.resume(last["id"])
        else:
            sm.start_new()
    except Exception as e:
        print("Workspace switch error:", e)

    return {
        "status": "ok",
        "path": str(curr),
        "name": curr.name
    }


@router.post("/pick-folder")
def pick_folder_dialog() -> Dict[str, Any]:
    """Opens native OS directory chooser (Zenity or Tkinter) on host desktop."""
    import shutil
    display = os.environ.get("DISPLAY", ":0")
    
    # Dynamic fallback: Desktop if exists, else home
    default_dir = Path.home() / "Desktop"
    if not default_dir.exists():
        default_dir = Path.home()
    default_dir = str(default_dir)

    # 1. Try zenity first
    if shutil.which("zenity"):
        try:
            res = subprocess.run(
                ["zenity", "--file-selection", "--directory", "--title=Select Project Folder", f"--filename={default_dir}/"],
                capture_output=True, text=True, timeout=120, env=dict(os.environ, DISPLAY=display)
            )
            if res.returncode == 0 and res.stdout.strip():
                folder = res.stdout.strip()
                if os.path.isdir(folder):
                    return {"status": "ok", "path": folder, "name": Path(folder).name}
            elif res.returncode == 1:
                return {"status": "cancel", "message": "Cancelled"}
        except Exception:
            pass

    # 2. Try tkinter
    try:
        script = f"""
import os, sys, tkinter as tk, tkinter.filedialog as fd
try:
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    folder = fd.askdirectory(title='Select Project Folder / Workspace', initialdir='{default_dir}')
    root.destroy()
    if folder and os.path.isdir(folder):
        print(folder)
except Exception:
    pass
"""
        res = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=120, env=dict(os.environ, DISPLAY=display)
        )
        if res.returncode == 0 and res.stdout.strip():
            folder = res.stdout.strip().splitlines()[-1].strip()
            if os.path.isdir(folder):
                return {"status": "ok", "path": folder, "name": Path(folder).name}
    except Exception as err:
        return {"status": "error", "message": str(err)}

    return {"status": "cancel", "message": "No folder selected"}


@router.get("/browse-folders")
def browse_folders(dir_path: str = "") -> Dict[str, Any]:
    """Lists directories for folder picker dialog."""
    if not dir_path:
        base = Path.home() / "Desktop"
        if not base.exists():
            base = Path.home()
    else:
        base = Path(os.path.expanduser(dir_path)).resolve()

    if not base.exists() or not base.is_dir():
        base = Path.home()

    folders = []
    ignored = {".git", "__pycache__", ".venv", "node_modules"}

    try:
        for entry in sorted(list(os.scandir(base)), key=lambda e: e.name.lower()):
            if entry.is_dir() and entry.name not in ignored and not entry.name.startswith("."):
                folders.append({
                    "name": entry.name,
                    "path": str(Path(entry.path).resolve())
                })
    except Exception:
        pass

    parent = str(base.parent) if base != base.parent else ""
    return {
        "current_path": str(base),
        "parent_path": parent,
        "folders": folders
    }

@router.get("/tree")
def get_tree(dir_path: str = "") -> List[Dict[str, Any]]:
    target_dir = safe_resolve(dir_path)
    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    items = []
    ignored = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache", ".ruff_cache"}

    try:
        entries = sorted(list(os.scandir(target_dir)), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries:
            rel_path = str(Path(entry.path).relative_to(CURRENT_WORKSPACE))
            is_dir = entry.is_dir()
            is_ignored = entry.name in ignored

            item = {
                "name": entry.name,
                "path": rel_path,
                "is_dir": is_dir,
                "is_hidden": entry.name.startswith("."),
                "is_ignored": is_ignored
            }
            if not is_dir:
                try:
                    stat = entry.stat()
                    item["size"] = stat.st_size
                except Exception:
                    item["size"] = 0
            items.append(item)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return items

@router.get("/file")
def read_file(path: str = Query(...)) -> Dict[str, Any]:
    file_path = safe_resolve(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        content = file_path.read_text(encoding="utf-8")
        return {"path": path, "content": content, "size": len(content)}
    except UnicodeDecodeError:
        return {"path": path, "content": "[Binary or non-UTF-8 file cannot be displayed]", "is_binary": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/file")
def save_file(req: SaveFileRequest) -> Dict[str, Any]:
    file_path = safe_resolve(req.path)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(req.content, encoding="utf-8")
        return {"status": "ok", "path": req.path, "bytes_written": len(req.content)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/create")
def create_item(req: CreateItemRequest) -> Dict[str, Any]:
    target = safe_resolve(req.path)
    if target.exists():
        raise HTTPException(status_code=400, detail="Item already exists")
    try:
        if req.type == "folder":
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        return {"status": "ok", "path": req.path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/delete")
def delete_item(req: DeleteItemRequest) -> Dict[str, Any]:
    target = safe_resolve(req.path)
    curr = get_current_workspace()
    if target == curr:
        raise HTTPException(status_code=400, detail="Cannot delete workspace root directory")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    try:
        if target.is_dir():
            import shutil
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"status": "ok", "path": req.path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/rename")
def rename_item(req: RenameItemRequest) -> Dict[str, Any]:
    old_target = safe_resolve(req.old_path)
    new_target = safe_resolve(req.new_path)
    if not old_target.exists():
        raise HTTPException(status_code=404, detail="Source item not found")
    if new_target.exists():
        raise HTTPException(status_code=400, detail="Destination already exists")
    try:
        new_target.parent.mkdir(parents=True, exist_ok=True)
        old_target.rename(new_target)
        return {"status": "ok", "old_path": req.old_path, "new_path": req.new_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/search")
def search_workspace(req: SearchRequest) -> List[Dict[str, Any]]:
    if not req.query:
        return []
    query = req.query if req.case_sensitive else req.query.lower()
    results = []
    ignored = {".git", "__pycache__", ".venv", "node_modules"}

    for root, dirs, files in os.walk(CURRENT_WORKSPACE):
        dirs[:] = [d for d in dirs if d not in ignored]
        for f in files:
            if f.endswith((".pyc", ".png", ".jpg", ".jpeg", ".ico", ".bin", ".tar", ".gz")):
                continue
            file_path = Path(root) / f
            try:
                if file_path.stat().st_size > 2_000_000:
                    continue
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()
                rel_path = str(file_path.relative_to(CURRENT_WORKSPACE))
                for i, line in enumerate(lines, 1):
                    match_line = line if req.case_sensitive else line.lower()
                    if query in match_line:
                        results.append({
                            "path": rel_path,
                            "line": i,
                            "content": line.strip()[:200]
                        })
                        if len(results) >= 100:
                            return results
            except Exception:
                continue
    return results

@router.get("/all-files")
def get_all_files() -> List[Dict[str, str]]:
    ignored = {".git", "__pycache__", ".venv", "node_modules"}
    results = []
    for root, dirs, files in os.walk(CURRENT_WORKSPACE):
        dirs[:] = [d for d in dirs if d not in ignored]
        for f in files:
            if f.endswith((".pyc", ".png", ".jpg", ".jpeg", ".ico", ".bin", ".tar", ".gz")):
                continue
            file_path = Path(root) / f
            rel_path = str(file_path.relative_to(CURRENT_WORKSPACE))
            results.append({"name": f, "path": rel_path})
            if len(results) >= 500:
                break
    return results

@router.get("/git-status")
def git_status() -> Dict[str, Any]:
    try:
        check = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(CURRENT_WORKSPACE),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if check.returncode != 0:
            return {"is_git": False, "branch": "", "modified": [], "count": 0}

        res = subprocess.run(
            ["git", "status", "--porcelain", "-b"],
            cwd=str(CURRENT_WORKSPACE),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        lines = res.stdout.strip().splitlines()
        branch = "main"
        modified_files = []
        if lines and lines[0].startswith("##"):
            branch = lines[0][3:].split("...")[0].strip()
            lines = lines[1:]

        for l in lines:
            if len(l) >= 4:
                status_code = l[:2].strip()
                fpath = l[3:].strip()
                modified_files.append({"status": status_code, "path": fpath})

        return {
            "is_git": True,
            "branch": branch,
            "modified": modified_files,
            "count": len(modified_files)
        }
    except Exception as e:
        return {"is_git": False, "branch": "", "modified": [], "count": 0, "error": str(e)}

@router.post("/git-commit")
def git_commit(req: CommitRequest) -> Dict[str, Any]:
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Commit message cannot be empty")
    try:
        subprocess.run(["git", "add", "."], cwd=str(CURRENT_WORKSPACE), check=True)
        res = subprocess.run(
            ["git", "commit", "-m", req.message],
            cwd=str(CURRENT_WORKSPACE),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return {"status": "ok", "output": res.stdout}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=e.stderr or str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/recent-projects")
def get_recent_projects_endpoint() -> List[Dict[str, Any]]:
    from vallen_cli.core.config import get_projects_db
    pdb = get_projects_db()
    projs = pdb.all_projects()
    curr = get_current_workspace()
    res = []
    seen = set()

    # Active workspace at index 0 if valid
    curr_str = str(curr.resolve())
    if curr.exists() and not curr_str.startswith("/tmp/pytest"):
        seen.add(curr_str)
        res.append({
            "name": curr.name,
            "path": curr_str,
            "is_active": True
        })

    for p in projs:
        path_str = p.get("path", "")
        if path_str and not path_str.startswith("/tmp/pytest") and path_str not in seen:
            p_obj = Path(path_str).resolve()
            if p_obj.exists() and p_obj.is_dir():
                seen.add(path_str)
                res.append({
                    "name": p.get("name") or p_obj.name,
                    "path": path_str,
                    "is_active": (path_str == curr_str)
                })
    return res

@router.post("/clear-recent-projects")
def clear_recent_projects_endpoint() -> Dict[str, str]:
    from vallen_cli.core.config import get_projects_db
    pdb = get_projects_db()
    pdb.clear_all()
    return {"status": "ok", "message": "Recent projects cleared"}

@router.post("/remove-recent-project")
def remove_recent_project_endpoint(req: RemoveRecentProjectRequest) -> Dict[str, str]:
    from vallen_cli.core.config import get_projects_db
    pdb = get_projects_db()
    pdb.remove_project(req.path)
    return {"status": "ok", "path": req.path}

@router.get("/git-file-diff")
def git_file_diff(path: str = Query(...)) -> Dict[str, Any]:
    target = safe_resolve(path)
    curr = get_current_workspace()
    rel_path = str(target.relative_to(curr))
    try:
        res = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            cwd=str(curr),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        original = res.stdout if res.returncode == 0 else ""
        modified = target.read_text(encoding="utf-8", errors="ignore") if target.exists() else ""
        from .diff_engine import compute_diff
        diff_data = compute_diff(original, modified, rel_path)
        return {
            "path": rel_path,
            "original": original,
            "modified": modified,
            "additions": diff_data["additions"],
            "deletions": diff_data["deletions"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
