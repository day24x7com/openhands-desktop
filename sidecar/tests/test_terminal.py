"""Tests for interactive PTY terminal sessions (real processes, no mocks)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from app.terminal import PtyUnavailable, SessionRegistry, create_session

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX backend; Windows uses ConPTY")


def read_until(session, needle: str, timeout: float = 10.0) -> str:
    """Collect PTY output until ``needle`` appears (or the timeout expires)."""
    chunks: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chunk = session.read(4096)
        if chunk:
            chunks.append(chunk)
            if needle in "".join(chunks):
                return "".join(chunks)
        else:
            time.sleep(0.02)
    return "".join(chunks)


def test_session_runs_commands_in_workspace(tmp_path: Path) -> None:
    session = create_session(tmp_path, shell="bash", cols=120, rows=40)
    try:
        assert session.alive
        # Wait for the *resolved* path, not the echoed command line (the PTY echoes
        # the typed text too, so a marker like "cwd-is:" would match too early).
        expected = f"cwd-is:{tmp_path}"
        session.write("printf 'hello-pty\\n'; echo " + expected + "\n")
        output = read_until(session, expected + "\r\n")
        assert "hello-pty" in output
        assert expected in output
    finally:
        session.close()


def test_session_keeps_state_between_writes(tmp_path: Path) -> None:
    """A real shell, not one command per request: env vars and cwd persist."""
    session = create_session(tmp_path, shell="bash")
    try:
        session.write("export OHD_TEST_VAR=persisted\n")
        read_until(session, "persisted")
        session.write("echo var=$OHD_TEST_VAR\n")
        assert "var=persisted" in read_until(session, "var=persisted")

        sub = tmp_path / "subdir"
        sub.mkdir()
        session.write(f"cd {sub} && echo in-dir\n")
        assert "in-dir" in read_until(session, "in-dir")
    finally:
        session.close()


def test_resize_does_not_error(tmp_path: Path) -> None:
    session = create_session(tmp_path, shell="bash", cols=80, rows=24)
    try:
        session.resize(160, 50)
        session.write("echo resized\n")
        assert "resized" in read_until(session, "resized")
    finally:
        session.close()


def test_close_stops_the_session(tmp_path: Path) -> None:
    session = create_session(tmp_path, shell="bash")
    session.close()
    time.sleep(0.2)
    assert not session.alive


def test_registry_tracks_and_closes_sessions(tmp_path: Path) -> None:
    registry = SessionRegistry()
    session = create_session(tmp_path, shell="bash")
    registry.add("abc", session)
    assert registry.get("abc") is session
    registry.remove("abc")
    assert registry.get("abc") is None
    assert not session.alive


def test_unsupported_shell_name_falls_back(tmp_path: Path) -> None:
    session = create_session(tmp_path, shell="bash")
    try:
        session.write("echo fallback-ok\n")
        assert "fallback-ok" in read_until(session, "fallback-ok")
    finally:
        session.close()


def test_windows_backend_reports_missing_dependency(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """On Windows without pywinpty we must fail loudly, not silently degrade."""
    import app.terminal as terminal

    monkeypatch.setattr(terminal, "IS_WINDOWS", True)

    class _BlockPyWinPty:
        def find_module(self, name: str, path=None):  # noqa: ARG002
            return None

    monkeypatch.setitem(sys.modules, "winpty", None)
    with pytest.raises(PtyUnavailable):
        terminal.create_session(tmp_path, shell="powershell")
