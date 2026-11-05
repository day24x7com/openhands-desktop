"""Shell execution with Windows-aware shell selection.

Uses ``subprocess`` directly (no shell=True) so arguments cannot be injected, and
streams output with a timeout that kills the whole process tree — on Windows a Job
Object-free approach: ``CREATE_NEW_PROCESS_GROUP`` + ``taskkill /T`` fallback.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT_BYTES = 200_000
DEFAULT_TIMEOUT = 180


@dataclass
class ShellResult:
    ok: bool
    output: str
    exit_code: int
    duration_ms: int
    truncated: bool = False
    timed_out: bool = False


def _shell_argv(shell: str, command: str) -> list[str]:
    """Build an argv for the requested shell without going through a shell string."""
    if shell == "powershell":
        exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        return [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
    if shell == "cmd":
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", command]
    if shell == "wsl":
        return ["wsl.exe", "bash", "-lc", command]
    bash = shutil.which("bash") or shutil.which("sh") or "/bin/sh"
    return [bash, "-lc", command]


def default_shell() -> str:
    if sys.platform == "win32":
        return "powershell"
    return "bash"


def detect_available_shells() -> list[str]:
    shells = []
    for name, probes in {
        "powershell": ["pwsh", "powershell"],
        "cmd": ["cmd.exe"],
        "bash": ["bash", "sh"],
        "wsl": ["wsl.exe"],
    }.items():
        if any(shutil.which(p) for p in probes):
            shells.append(name)
    return shells


def run_command(
    command: str,
    cwd: Path | str,
    shell: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> ShellResult:
    """Execute a command and capture combined stdout/stderr."""
    shell = shell or default_shell()
    argv = _shell_argv(shell, command)
    started = time.monotonic()
    merged_env = {**os.environ, **(env or {})}
    merged_env.setdefault("GIT_PAGER", "cat")
    merged_env.setdefault("TERM", "dumb")
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=merged_env,
            text=False,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            start_new_session=sys.platform != "win32",
        )
    except (FileNotFoundError, OSError) as exc:
        return ShellResult(False, f"Failed to start shell: {exc}", 127, 0)

    chunks: list[bytes] = []
    total = 0
    truncated = False

    def reader() -> None:
        nonlocal total, truncated
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            if total < MAX_OUTPUT_BYTES:
                chunks.append(chunk)
                total += len(chunk)
            else:
                truncated = True

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
    thread.join(timeout=5)
    output = b"".join(chunks).decode("utf-8", errors="replace")
    if truncated:
        output += f"\n… output truncated at {MAX_OUTPUT_BYTES} bytes"
    duration = int((time.monotonic() - started) * 1000)
    exit_code = proc.returncode if proc.returncode is not None else -1
    if timed_out:
        output += f"\nCommand timed out after {timeout}s and was terminated."
    return ShellResult(
        ok=exit_code == 0 and not timed_out,
        output=output.strip(),
        exit_code=exit_code,
        duration_ms=duration,
        truncated=truncated,
        timed_out=timed_out,
    )


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), 9)  # type: ignore[attr-defined]
    except Exception:
        proc.kill()
