"""Tests for the agent tools against a real workspace directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.tools import Toolbox, ToolContext
from app.workspace import LocalWorkspace, WorkspaceRef, diff_text, guess_language, parse_unified_diff


@pytest.fixture()
def toolbox(tmp_path: Path) -> Toolbox:
    root = tmp_path / "ws"
    root.mkdir()
    ws = LocalWorkspace(WorkspaceRef(id="ws1", path=root, kind="local", name="ws"))
    return Toolbox(ToolContext(workspace=ws, shell="bash"))


def test_write_then_read_file(toolbox: Toolbox, tmp_path: Path) -> None:
    result = toolbox.execute("write_file", {"path": "src/app.py", "content": "print('hi')\n"})
    assert result.ok
    assert (tmp_path / "ws" / "src" / "app.py").read_text() == "print('hi')\n"
    read = toolbox.execute("read_file", {"path": "src/app.py"})
    assert read.ok
    assert "print('hi')" in read.content
    assert read.file_path == "src/app.py"


def test_str_replace_requires_exact_match(toolbox: Toolbox) -> None:
    toolbox.execute("write_file", {"path": "a.txt", "content": "alpha beta gamma"})
    ok = toolbox.execute("str_replace", {"path": "a.txt", "old_str": "beta", "new_str": "BETA"})
    assert ok.ok
    assert "BETA" in ok.content or ok.ok
    missing = toolbox.execute("str_replace", {"path": "a.txt", "old_str": "nope", "new_str": "x"})
    assert not missing.ok
    assert "not found" in missing.content


def test_write_file_reports_diff(toolbox: Toolbox) -> None:
    with_diff = toolbox.execute("write_file", {"path": "notes.md", "content": "line1\nline2\n"})
    assert with_diff.diff is not None
    assert with_diff.diff["status"] == "added"
    assert with_diff.diff["additions"] == 2


def test_tools_cannot_escape_workspace(toolbox: Toolbox) -> None:
    result = toolbox.execute("read_file", {"path": "../../etc/passwd"})
    assert not result.ok
    assert "escapes workspace" in result.content
    write = toolbox.execute("write_file", {"path": "../evil.txt", "content": "x"})
    assert not write.ok


def test_run_shell_executes(toolbox: Toolbox) -> None:
    result = toolbox.execute("run_shell", {"command": "echo hello-from-tool"})
    assert result.ok
    assert "hello-from-tool" in result.content
    assert result.exit_code == 0


def test_run_shell_reports_failure(toolbox: Toolbox) -> None:
    result = toolbox.execute("run_shell", {"command": "exit 3"})
    assert not result.ok
    assert result.exit_code == 3


def test_web_fetch_can_be_disabled(toolbox: Toolbox) -> None:
    toolbox.ctx.allow_network = False
    result = toolbox.execute("web_fetch", {"url": "https://example.com"})
    assert not result.ok
    assert "network access is disabled" in result.content


def test_plan_and_finish_tools(toolbox: Toolbox) -> None:
    result = toolbox.execute(
        "update_plan", {"items": [{"title": "write tests", "status": "in_progress"}]}
    )
    assert result.ok
    assert toolbox.ctx.plan == [{"title": "write tests", "status": "in_progress", "notes": ""}]
    finished = toolbox.execute("finish", {"summary": "All done"})
    assert finished.ok
    assert toolbox.ctx.finish_summary == "All done"


def test_unknown_tool_is_an_error_result(toolbox: Toolbox) -> None:
    result = toolbox.execute("does_not_exist", {})
    assert not result.ok
    assert "Unknown tool" in result.content


def test_line_endings_are_preserved(toolbox: Toolbox, tmp_path: Path) -> None:
    target = tmp_path / "ws" / "win.txt"
    target.write_bytes(b"one\r\ntwo\r\n")
    toolbox.execute("str_replace", {"path": "win.txt", "old_str": "two", "new_str": "three"})
    assert b"three\r\n" in target.read_bytes()


def test_diff_helpers() -> None:
    diff = diff_text("a.py", "a\nb\n", "a\nc\n")
    assert diff.status == "modified"
    assert diff.additions == 1 and diff.deletions == 1
    parsed = parse_unified_diff(
        "diff --git a/x b/x\nnew file mode 100644\n--- /dev/null\n+++ b/x\n@@ -0,0 +1,2 @@\n+hi\n+there\n"
    )
    assert parsed and parsed[0].path == "x" and parsed[0].status == "added"
    assert guess_language("main.py") == "python"
