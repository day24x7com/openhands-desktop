"""Agent tools exposed to the LLM (spec §5.4).

Each tool has an OpenAI-style JSON schema plus a Python implementation bound to a
workspace. Tools never touch the network unless the user allowed it, and every
filesystem access goes through the workspace path guard.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .safety import PathGuardError
from .workspace import BaseWorkspace, WorkspaceError, diff_text, guess_language

MAX_READ_LINES = 2000


@dataclass
class ToolResult:
    ok: bool
    content: str
    exit_code: int | None = None
    duration_ms: int | None = None
    file_path: str | None = None
    diff: dict[str, Any] | None = None


@dataclass
class ToolContext:
    workspace: BaseWorkspace
    shell: str
    allow_network: bool = True
    plan: list[dict[str, Any]] | None = None
    finish_summary: str | None = None


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Run a shell command in the workspace directory and return its combined stdout/stderr "
                "and exit code. Use it to build, test and inspect the project."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute."},
                    "timeout_seconds": {"type": "integer", "default": 120},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file from the workspace. Line numbers are prefixed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "default": 1},
                    "end_line": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with full content. Prefer str_replace for small edits.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "str_replace",
            "description": "Replace the first exact occurrence of old_str with new_str in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_str": {"type": "string"},
                    "new_str": {"type": "string"},
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List the workspace file tree (honours .gitignore-style skips).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "."},
                    "depth": {"type": "integer", "default": 2},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a public URL and return its readable text. Use for docs/research.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_plan",
            "description": "Maintain the visible task plan. Send the full list each time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "status": {"type": "string", "enum": ["todo", "in_progress", "done"]},
                                "notes": {"type": "string"},
                            },
                            "required": ["title", "status"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "think",
            "description": "Record a reasoning note for the user without taking any action.",
            "parameters": {
                "type": "object",
                "properties": {"thought": {"type": "string"}},
                "required": ["thought"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Finish the task and report a short summary of what was done.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    },
]

TOOL_NAMES = [t["function"]["name"] for t in TOOL_SCHEMAS]


def summarise_call(name: str, args: dict[str, Any]) -> str:
    """One-line description shown on the timeline action card."""
    if name == "run_shell":
        return args.get("command", "")
    if name in {"read_file", "list_files"}:
        return args.get("path", ".")
    if name == "write_file":
        return args.get("path", "")
    if name == "str_replace":
        return args.get("path", "")
    if name == "web_fetch":
        return args.get("url", "")
    if name == "update_plan":
        return f"{len(args.get('items') or [])} plan items"
    if name == "think":
        return (args.get("thought") or "")[:120]
    if name == "finish":
        return (args.get("summary") or "")[:160]
    return name


class Toolbox:
    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx
        self._impls: dict[str, Callable[[dict[str, Any]], ToolResult]] = {
            "run_shell": self._run_shell,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "str_replace": self._str_replace,
            "list_files": self._list_files,
            "web_fetch": self._web_fetch,
            "update_plan": self._update_plan,
            "think": self._think,
            "finish": self._finish,
        }

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        impl = self._impls.get(name)
        if impl is None:
            return ToolResult(False, f"Unknown tool {name!r}. Available: {', '.join(TOOL_NAMES)}")
        try:
            return impl(args)
        except (WorkspaceError, PathGuardError) as exc:
            return ToolResult(False, f"Error: {exc}")
        except Exception as exc:  # tool bugs must not kill the agent loop
            return ToolResult(False, f"Tool {name} failed: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------- shell
    def _run_shell(self, args: dict[str, Any]) -> ToolResult:
        command = str(args.get("command") or "").strip()
        if not command:
            return ToolResult(False, "Error: command is required")
        timeout = int(args.get("timeout_seconds") or 120)
        result = self.ctx.workspace.run(command, shell=self.ctx.shell, timeout=timeout)
        return ToolResult(
            ok=result.ok,
            content=result.output or "(no output)",
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )

    # -------------------------------------------------------------- files
    def _read_file(self, args: dict[str, Any]) -> ToolResult:
        path = str(args.get("path") or "")
        text, _ = self.ctx.workspace.read_text(path)
        lines = text.splitlines()
        start = max(int(args.get("start_line") or 1), 1)
        end = int(args.get("end_line") or min(len(lines), start + MAX_READ_LINES - 1))
        end = min(end, len(lines))
        numbered = "\n".join(f"{i:>5}\t{line}" for i, line in enumerate(lines[start - 1 : end], start=start))
        return ToolResult(True, numbered or "(empty file)", file_path=path)

    def _write_file(self, args: dict[str, Any]) -> ToolResult:
        path = str(args.get("path") or "")
        content = str(args.get("content") or "")
        before = ""
        eol = "lf"
        try:
            before, eol = self.ctx.workspace.read_text(path)
        except WorkspaceError:
            eol = "crlf" if self.ctx.workspace.root.joinpath(".gitattributes").exists() is False else "lf"
        self.ctx.workspace.write_text(path, content, eol=eol)
        diff = diff_text(path, before, content)
        verb = "Updated" if before else "Created"
        return ToolResult(
            True,
            f"{verb} {path} ({len(content.splitlines())} lines)",
            file_path=path,
            diff=diff.model_dump(mode="json"),
        )

    def _str_replace(self, args: dict[str, Any]) -> ToolResult:
        path = str(args.get("path") or "")
        old = str(args.get("old_str") or "")
        new = str(args.get("new_str") or "")
        try:
            before, eol = self.ctx.workspace.read_text(path)
        except WorkspaceError:
            return ToolResult(False, f"Error: cannot read {path}")
        if old not in before:
            return ToolResult(False, f"Error: old_str not found in {path}. Read the file again first.")
        after = before.replace(old, new, 1)
        self.ctx.workspace.write_text(path, after, eol=eol)
        diff = diff_text(path, before, after)
        return ToolResult(
            True,
            f"Edited {path} (+{diff.additions}/-{diff.deletions})",
            file_path=path,
            diff=diff.model_dump(mode="json"),
        )

    def _list_files(self, args: dict[str, Any]) -> ToolResult:
        path = str(args.get("path") or ".")
        depth = int(args.get("depth") or 2)
        nodes = self.ctx.workspace.tree(path, depth=depth)
        listing = "\n".join(f"{n.type[0]}\t{n.path}" for n in nodes[:500])
        return ToolResult(True, listing or "(empty directory)")

    # -------------------------------------------------------------- web
    def _web_fetch(self, args: dict[str, Any]) -> ToolResult:
        if not self.ctx.allow_network:
            return ToolResult(False, "Error: network access is disabled in settings")
        url = str(args.get("url") or "")
        if not re.match(r"^https?://", url):
            return ToolResult(False, "Error: only http(s) URLs are allowed")
        request = urllib.request.Request(url, headers={"User-Agent": "OpenHandsDesktop/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                raw = response.read(2_000_000).decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            return ToolResult(False, f"Error fetching {url}: {exc}")
        text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", raw, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        return ToolResult(True, f"# {url}\n\n{text[:20000]}")

    # ------------------------------------------------------ meta tools
    def _update_plan(self, args: dict[str, Any]) -> ToolResult:
        items = [
            {
                "title": str(item.get("title", "")),
                "status": item.get("status", "todo"),
                "notes": str(item.get("notes") or ""),
            }
            for item in args.get("items") or []
            if isinstance(item, dict)
        ]
        self.ctx.plan = items
        summary = ", ".join(f"{i['title']} [{i['status']}]" for i in items) or "(empty plan)"
        return ToolResult(True, f"Plan updated: {summary}")

    def _think(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(True, "Noted.")

    def _finish(self, args: dict[str, Any]) -> ToolResult:
        summary = str(args.get("summary") or "Task finished.")
        self.ctx.finish_summary = summary
        return ToolResult(True, summary)


def tool_call_to_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


__all__ = ["TOOL_SCHEMAS", "TOOL_NAMES", "ToolContext", "ToolResult", "Toolbox", "guess_language", "summarise_call"]
