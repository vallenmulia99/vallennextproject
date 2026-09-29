import asyncio
import fcntl
import os
import pty
import struct
import termios
from typing import Optional, Dict
from fastapi import WebSocket, WebSocketDisconnect

class TerminalSession:
    _registry: Dict[str, "TerminalSession"] = {}

    def __init__(self, websocket: WebSocket, cwd: str = "", session_id: str = "1"):
        self.websocket = websocket
        self.session_id = str(session_id)
        if not cwd:
            try:
                from .workspace_api import CURRENT_WORKSPACE
                cwd = str(CURRENT_WORKSPACE)
            except Exception:
                cwd = os.getcwd()
        self.cwd = cwd
        self.master_fd: Optional[int] = None
        self.pid: Optional[int] = None
        self.loop = asyncio.get_event_loop()
        TerminalSession._registry[self.session_id] = self

    def set_size(self, rows: int, cols: int):
        if self.master_fd is not None:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            try:
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except Exception:
                pass

    def write_input(self, data: str):
        if self.master_fd is not None:
            try:
                os.write(self.master_fd, data.encode("utf-8"))
            except Exception:
                pass

    async def start(self):
        await self.websocket.accept()

        # Spawn bash in PTY
        self.pid, self.master_fd = pty.fork()
        if self.pid == 0:
            # Child process
            os.chdir(self.cwd)
            os.environ["TERM"] = "xterm-256color"
            os.environ["COLORTERM"] = "truecolor"
            shell = os.environ.get("SHELL", "/bin/bash")
            os.execlp(shell, shell)
            os._exit(1)

        # Set non-blocking on master_fd
        flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
        fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        # Queue for reading output
        read_queue: asyncio.Queue[bytes] = asyncio.Queue()

        def on_readable():
            try:
                data = os.read(self.master_fd, 8192)
                if data:
                    read_queue.put_nowait(data)
                else:
                    self.loop.remove_reader(self.master_fd)
            except (BlockingIOError, InterruptedError):
                pass
            except Exception:
                try:
                    self.loop.remove_reader(self.master_fd)
                except Exception:
                    pass

        self.loop.add_reader(self.master_fd, on_readable)

        async def send_to_ws():
            try:
                while True:
                    data = await read_queue.get()
                    await self.websocket.send_bytes(data)
            except Exception:
                pass

        async def recv_from_ws():
            try:
                while True:
                    msg = await self.websocket.receive_json()
                    mtype = msg.get("type")
                    if mtype == "input":
                        data = msg.get("data", "")
                        if self.master_fd is not None:
                            os.write(self.master_fd, data.encode("utf-8"))
                    elif mtype == "resize":
                        rows = msg.get("rows", 24)
                        cols = msg.get("cols", 80)
                        self.set_size(rows, cols)
            except WebSocketDisconnect:
                pass
            except Exception:
                pass

        send_task = asyncio.create_task(send_to_ws())
        recv_task = asyncio.create_task(recv_from_ws())

        done, pending = await asyncio.wait(
            [send_task, recv_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

        self.cleanup()

    def cleanup(self):
        TerminalSession._registry.pop(self.session_id, None)

        if self.master_fd is not None:
            try:
                self.loop.remove_reader(self.master_fd)
            except Exception:
                pass
            try:
                os.close(self.master_fd)
            except Exception:
                pass
            self.master_fd = None

        if self.pid is not None:
            try:
                os.kill(self.pid, 9)
                os.waitpid(self.pid, os.WNOHANG)
            except Exception:
                pass
            self.pid = None


def get_terminal_session(session_id: str = "1") -> Optional[TerminalSession]:
    return TerminalSession._registry.get(str(session_id)) or next(iter(TerminalSession._registry.values()), None)
