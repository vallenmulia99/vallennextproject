import os
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .workspace_api import router as workspace_router
from .agent_bridge import router as agent_router
from .terminal_pty import TerminalSession

app = FastAPI(title="VALLEN IDE Backend", version="1.0.0")

# Allow CORS for localhost development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers
app.include_router(workspace_router)
app.include_router(agent_router)

# VALLEN CIHUY (PRD & System Blueprint Studio)
try:
    from vallen_cihuy.router import router as cihuy_router
    app.include_router(cihuy_router)
except Exception as e:
    print(f"Warning: could not load vallen_cihuy: {e}")

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "vallen-ide", "version": "1.0.0"}

# WebSocket Terminal PTY (Multi-terminal support)
@app.websocket("/ws/terminal")
@app.websocket("/ws/terminal/{term_id}")
async def terminal_endpoint(websocket: WebSocket, term_id: str = "1"):
    qp_id = websocket.query_params.get("id")
    final_id = qp_id or term_id or "1"
    session = TerminalSession(websocket, session_id=final_id)
    await session.start()

# Mount Static Web Assets (VALLEN CIHUY Studio & IDE)
from fastapi.responses import FileResponse

CIHUY_WEB_DIR = Path(__file__).parent.parent.parent / "vallen_cihuy" / "web"

@app.get("/cihuy")
@app.get("/cihuy/")
def serve_cihuy_studio():
    index_file = CIHUY_WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"detail": "Cihuy Studio index.html not found"}

if CIHUY_WEB_DIR.exists():
    app.mount("/cihuy", StaticFiles(directory=str(CIHUY_WEB_DIR), html=True), name="cihuy_static")

WEB_DIR = Path(__file__).parent.parent / "web"
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("vallen_ide.backend.main:app", host="0.0.0.0", port=8080, reload=True)
