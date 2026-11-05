"""Interactive terminal sessions (PTY) for the desktop terminal panel.

Two backends behind one interface:

* **Windows** — ``pywinpty``, which wraps the ConPTY API on Windows 10 1809+ and
  falls back to winpty on older systems.
* **POSIX** — the standard-library ``pty`` module (``fork`` + ``os.read``).

Sessions are kept in memory by the app and streamed to the renderer over a
WebSocket, so the terminal keeps its state (cwd, env, running program) between
keystrokes instead of re-running one command at a time.
"""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Protocol

IS_WINDOWS = sys.platform == "win32"


class PtyUnavailable(RuntimeError):
    """Raised when no PTY backend could be created on this machine."""


class TerminalSession(Protocol):
    """Minimal PTY surface used by the WebSocket handler."""

    @property
    def alive(self) -> bool: ...

    def read(self, size: int = 4096) -> str: ...

    def write(self, data: str) -> None: ...

    def resize(self, cols: int, rows: int) -> None: ...

    def close(self) -> None: ...


def _shell_command(shell: str) -> list[str]:
    if shell == "powershell":
        return ["pwsh" if _which("pwsh") else "powershell", "-NoLogo", "-NoProfile"]
    if shell == "cmd":
        return [os.environ.get("COMSPEC", "cmd.exe")]
    if shell == "wsl":
        return ["wsl.exe", "bash", "-l"]
    bash = _which("bash") or _which("sh") or "/bin/sh"
    return [bash, "-l"]


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


class _WinPtySession:
    """ConPTY/winpty backend for Windows."""

    def __init__(self, cwd: Path, shell: str, cols: int, rows: int) -> None:
        try:
            from winpty import PtyProcess  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - platform specific
            raise PtyUnavailable(
                "Interactive terminal requires the 'pywinpty' package (bundled with the installer)."
            ) from exc

        command = subprocess.list2cmdline(_shell_command(shell))
        try:
            self._pty = PtyProcess.spawn(command, dimensions=(rows, cols), cwd=str(cwd))
        except Exception as exc:  # pragma: no cover - platform specific
            raise PtyUnavailable(f"Could not start a ConPTY session: {exc}") from exc

    @property
    def alive(self) -> bool:
        return bool(getattr(self._pty, "isalive", lambda: False)())

    def read(self, size: int = 4096) -> str:
        try:
            return self._pty.read(size) or ""
        except (EOFError, OSError):
            return ""

    def write(self, data: str) -> None:
        try:
            self._pty.write(data)
        except (EOFError, OSError):
            pass

    def resize(self, cols: int, rows: int) -> None:
        try:
            self._pty.setwinsize(rows, cols)
        except Exception:  # pragma: no cover - best effort
            pass

    def close(self) -> None:
        try:
            self._pty.terminate(force=True)
        except Exception:  # pragma: no cover
            pass


class _PosixPtySession:
    """``pty.fork`` backend for macOS/Linux (and WSL-less POSIX hosts)."""

    def __init__(self, cwd: Path, shell: str, cols: int, rows: int) -> None:
        import fcntl
        import pty
        import struct
        import termios

        self._alive = True
        self._fd, child_fd = pty.openpty()
        self._pid = os.fork()
        if self._pid == 0:  # pragma: no cover - child process
            try:
                os.close(self._fd)
                os.setsid()
                os.dup2(child_fd, 0)
                os.dup2(child_fd, 1)
                os.dup2(child_fd, 2)
                if child_fd > 2:
                    os.close(child_fd)
                os.chdir(cwd)
                env = {**os.environ, "TERM": "xterm-256color", "PYTHONUNBUFFERED": "1"}
                os.execvpe(_shell_command(shell)[0], _shell_command(shell), env)
            finally:
                os._exit(1)  # noqa: SLF001

        os.close(child_fd)
        fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        os.set_blocking(self._fd, False)

    @property
    def alive(self) -> bool:
        return self._alive

    def read(self, size: int = 4096) -> str:
        try:
            data = os.read(self._fd, size)
        except BlockingIOError:
            return ""
        except OSError as exc:
            if exc.errno in (errno.EIO, errno.EBADF):
                self._alive = False
            return ""
        if not data:
            self._alive = False
            return ""
        return data.decode("utf-8", errors="replace")

    def write(self, data: str) -> None:
        try:
            os.write(self._fd, data.encode("utf-8", errors="replace"))
        except OSError:
            self._alive = False

    def resize(self, cols: int, rows: int) -> None:
        import fcntl
        import struct
        import termios

        try:
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def close(self) -> None:
        self._alive = False
        try:
            os.kill(self._pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            os.waitpid(self._pid, os.WNOHANG)
        except OSError:
            pass
        try:
            os.close(self._fd)
        except OSError:
            pass


def create_session(cwd: Path, shell: str = "bash", cols: int = 100, rows: int = 30) -> TerminalSession:
    """Create a PTY-backed shell rooted at ``cwd``."""
    if IS_WINDOWS:
        return _WinPtySession(cwd, shell, cols, rows)
    return _PosixPtySession(cwd, shell, cols, rows)


class SessionRegistry:
    """Owns live terminal sessions so the app can tear them all down on exit."""

    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.Lock()

    def add(self, session_id: str, session: TerminalSession) -> None:
        with self._lock:
            self._sessions[session_id] = session

    def get(self, session_id: str) -> TerminalSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            session.close()

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()
