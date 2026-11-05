"""Agent runtime: one background thread per conversation.

Responsibilities (spec §4.2, §5.3, §5.4):

* turn user messages into an LLM tool-calling loop over the workspace
* persist every step as an event and push it to WebSocket subscribers
* gate risky shell commands behind an approval dialog
* honour Stop/Pause within a couple of seconds (spec §15.5)
* queue follow-up user messages while the agent is busy (FR-3.5)
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from .db import Database
from .llm import LLMClient, LlmError, ToolCall, estimate_cost
from .models import ConversationEvent, utcnow
from .safety import classify_command
from .tools import TOOL_SCHEMAS, Toolbox, ToolContext, summarise_call
from .workspace import BaseWorkspace, WorkspaceError

SYSTEM_PROMPT = """You are OpenHands, an autonomous software engineer running inside a desktop app on \
the user's own computer. You work in the workspace directory `{workspace}` using the tools provided.

Rules:
- Inspect before you edit: list files / read a file before modifying it.
- Make focused changes, then verify them: run the project's tests, linter or a quick command.
- Shell is {shell!r}. Use its syntax (e.g. PowerShell cmdlets on Windows, unless bash is selected).
- Never run destructive commands (recursive deletes, formatting, force pushes, privilege escalation) \
without explaining why; the user must approve them.
- Keep `update_plan` current for multi-step work so the user can follow along in the UI.
- When the task is complete, call `finish` with a short summary of what changed and how it was verified.
- Be concise in prose; put actions in tool calls, not in prose.
{extra}"""

TOOL_LOOP_HINT = (
    "Continue with the next tool call. Available tools: "
    + ", ".join(t["function"]["name"] for t in TOOL_SCHEMAS)
)


class AgentRuntime:
    """Owns the thread, control flags and event emission for one conversation."""

    def __init__(self, db: Database, conversation_id: str) -> None:
        self.db = db
        self.conversation_id = conversation_id
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._approvals: dict[str, threading.Event] = {}
        self._approvals_lock = threading.Lock()
        self._queue: list[dict[str, Any]] = []
        self._queue_lock = threading.Lock()
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    # ------------------------------------------------------------ events
    def subscribe(self, listener: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def emit(self, event_type: str, **fields: Any) -> dict[str, Any]:
        event = ConversationEvent(
            conversation_id=self.conversation_id, type=event_type, **fields
        )
        stored = self.db.append_event(event.to_wire())
        for listener in list(self._listeners):
            try:
                listener(stored)
            except Exception:
                self._listeners.remove(listener)
        return stored

    # ----------------------------------------------------------- control
    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def submit(self, content: str, attachments: list[dict[str, Any]] | None = None) -> None:
        with self._queue_lock:
            self._queue.append({"content": content, "attachments": attachments or []})
        if not self.busy:
            self.start()

    def queued_count(self) -> int:
        with self._queue_lock:
            return len(self._queue)

    def start(self) -> None:
        if self.busy:
            return
        self._stop.clear()
        self._pause.clear()
        self._thread = threading.Thread(target=self._run, name=f"agent-{self.conversation_id[:8]}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._pause.clear()
        self._release_all_approvals(approved=False)
        with self._queue_lock:
            self._queue.clear()

    def pause(self) -> None:
        self._pause.set()
        self.db.update_conversation(self.conversation_id, status="paused")
        self.emit("status", status="paused", detail="Paused by user")

    def resume(self) -> None:
        self._pause.clear()
        if self.busy:
            self.db.update_conversation(self.conversation_id, status="running")
            self.emit("status", status="running", detail="Resumed")
        else:
            self.start()

    def resolve_approval(self, approval_id: str, approved: bool, remember: bool = False) -> bool:
        with self._approvals_lock:
            waiter = self._approvals.get(approval_id)
        record = self.db.decide_approval(approval_id, approved, remember)
        if record is None:
            return False
        if waiter is not None:
            waiter.set()
        return True

    def _release_all_approvals(self, approved: bool) -> None:
        with self._approvals_lock:
            items = list(self._approvals.items())
        for approval_id, waiter in items:
            self.db.decide_approval(approval_id, approved)
            waiter.set()

    # ------------------------------------------------------- agent loop
    def _run(self) -> None:
        try:
            self._loop()
        except Exception as exc:  # pragma: no cover - defensive
            self.emit("error", message=f"Agent crashed: {type(exc).__name__}: {exc}", recoverable=False)
            self.db.update_conversation(self.conversation_id, status="error")
        finally:
            self._thread = None

    def _load_context(self) -> dict[str, Any]:
        conversation = self.db.get_conversation(self.conversation_id)
        if conversation is None:
            raise WorkspaceError("conversation not found")
        workspace = self.db.get_workspace(conversation["workspace_id"])
        if workspace is None:
            raise WorkspaceError("workspace not found")
        return {**conversation, "workspace": workspace}

    def _build_llm(self, conversation: dict[str, Any]) -> LLMClient:
        from .services import build_llm_for_conversation  # local import avoids a cycle

        return build_llm_for_conversation(self.db, conversation)

    def _loop(self) -> None:
        conversation = self._load_context()
        self.db.update_conversation(self.conversation_id, status="running")
        self.emit("status", status="running", detail="Agent started")

        workspace = self._make_workspace(conversation)
        try:
            llm = self._build_llm(conversation)
        except Exception as exc:
            self.emit("error", message=str(exc), recoverable=True)
            self.db.update_conversation(self.conversation_id, status="error")
            return

        plan: list[dict[str, Any]] = []
        ctx = ToolContext(
            workspace=workspace,
            shell=conversation.get("shell") or "powershell",
            allow_network=True,
            plan=plan,
        )
        toolbox = Toolbox(ctx)
        messages = self._initial_messages(conversation)
        steps = 0
        max_steps = 40

        while True:
            if self._stop.is_set():
                self.emit("status", status="idle", detail="Stopped by user")
                self.db.update_conversation(self.conversation_id, status="idle")
                return
            while self._pause.is_set() and not self._stop.is_set():
                time.sleep(0.1)

            for item in self._drain_queue():
                messages.append({"role": "user", "content": item["content"]})

            if steps >= max_steps:
                self.emit("error", message="Step limit reached; stopping to protect your budget.", recoverable=True)
                break
            steps += 1

            try:
                reply = llm.complete(messages, TOOL_SCHEMAS)
            except LlmError as exc:
                self.emit("error", message=str(exc), recoverable=True)
                self.db.update_conversation(self.conversation_id, status="error")
                return

            if reply.text:
                self._persist_assistant(messages, reply.text, reply.tool_calls, reply.model)
                self.emit("message", role="assistant", content=reply.text)
            elif reply.tool_calls:
                self._persist_assistant(messages, "", reply.tool_calls, reply.model)

            self._record_usage(reply)

            if not reply.tool_calls:
                break

            for call in reply.tool_calls:
                if self._stop.is_set():
                    break
                result = self._execute_tool(call, toolbox, conversation, ctx, plan)
                if result is None:
                    self.db.update_conversation(self.conversation_id, status="idle")
                    return
                tool_message = {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": result}
                messages.append(tool_message)

            if ctx.finish_summary is not None:
                break

        summary = ctx.finish_summary or "Task finished."
        self.emit("message", role="assistant", content=summary)
        self.emit("status", status="done", detail="Finished")
        self.db.update_conversation(self.conversation_id, status="done")
        workspace.cleanup()

    # ---------------------------------------------------------- helpers
    def _make_workspace(self, conversation: dict[str, Any]) -> BaseWorkspace:
        from .services import workspace_from_row

        return workspace_from_row(conversation["workspace"], conversation.get("mode") or "local")

    def _initial_messages(self, conversation: dict[str, Any]) -> list[dict[str, Any]]:
        from .services import workspace_from_row

        workspace = workspace_from_row(conversation["workspace"], conversation.get("mode") or "local")
        extra = conversation.get("system_suffix") or ""
        system = SYSTEM_PROMPT.format(
            workspace=str(workspace.root), shell=conversation.get("shell") or "powershell", extra=extra
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for event in self.db.list_events(self.conversation_id):
            if event["type"] != "message":
                continue
            role = event.get("role")
            if role == "user":
                attachments = event.get("attachments") or []
                text = event.get("content") or ""
                if attachments:
                    text += _describe_attachments(attachments)
                messages.append({"role": "user", "content": text})
            elif role == "assistant":
                messages.append({"role": "assistant", "content": event.get("content") or ""})
        if len(messages) == 1:
            messages.append({"role": "user", "content": TOOL_LOOP_HINT})
        else:
            messages.append({"role": "user", "content": "Continue the task with the next tool call."})
        return messages

    def _persist_assistant(
        self, messages: list[dict[str, Any]], text: str, calls: list[ToolCall], model: str
    ) -> None:
        if calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": text,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in calls
                    ],
                }
            )
        else:
            messages.append({"role": "assistant", "content": text})

    def _record_usage(self, reply: Any) -> None:
        conversation = self.db.get_conversation(self.conversation_id) or {}
        cost = estimate_cost(reply.model or "", reply.usage.prompt_tokens, reply.usage.completion_tokens)
        total_tokens = (
            int(conversation.get("tokens_total") or 0)
            + reply.usage.prompt_tokens
            + reply.usage.completion_tokens
        )
        total_cost = round(float(conversation.get("cost_total") or 0) + cost, 6)
        self.db.update_conversation(self.conversation_id, tokens_total=total_tokens, cost_total=total_cost)
        self.emit(
            "usage",
            prompt_tokens=reply.usage.prompt_tokens,
            completion_tokens=reply.usage.completion_tokens,
            cost_usd=round(cost, 6),
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            model=reply.model,
        )
        limit = self.db.get_setting("settings", {}).get("max_cost_usd_per_conversation")
        if limit and total_cost > float(limit):
            self.emit("error", message=f"Budget limit of ${limit} reached; stopping.", recoverable=True)
            self.stop()

    def _execute_tool(
        self,
        call: ToolCall,
        toolbox: Toolbox,
        conversation: dict[str, Any],
        ctx: ToolContext,
        plan: list[dict[str, Any]],
    ) -> str | None:
        summary = summarise_call(call.name, call.arguments)
        self.emit(
            "action",
            tool=call.name,
            call_id=call.id,
            summary=summary,
            args=call.arguments,
        )

        if call.name == "run_shell" and conversation.get("confirm_risky", 1):
            verdict = classify_command(str(call.arguments.get("command") or ""))
            remembered = self.db.list_remembered_commands(self.conversation_id)
            if verdict.risky and str(call.arguments.get("command")) not in remembered:
                approved = self._request_approval(call, verdict.reason)
                if approved is None:
                    self.emit("status", status="idle", detail="Stopped while waiting for approval")
                    return None
                if not approved:
                    content = "User denied this command. Do not retry it; ask what to do instead."
                    self.emit(
                        "observation", tool=call.name, call_id=call.id, ok=False, content=content, duration_ms=0
                    )
                    return content

        started = time.monotonic()
        result = toolbox.execute(call.name, call.arguments)
        duration = int((time.monotonic() - started) * 1000)
        self.emit(
            "observation",
            tool=call.name,
            call_id=call.id,
            ok=result.ok,
            content=result.content,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms or duration,
            file_path=result.file_path,
        )
        if call.name == "update_plan":
            self.emit("plan", items=ctx.plan or [])
        if call.name == "think":
            self.emit("thinking", content=str(call.arguments.get("thought") or ""))
        if call.name == "finish":
            ctx.finish_summary = result.content
        return result.content

    def _request_approval(self, call: ToolCall, reason: str) -> bool | None:
        approval_id = uuid.uuid4().hex
        waiter = threading.Event()
        with self._approvals_lock:
            self._approvals[approval_id] = waiter
        action = {
            "type": "action",
            "tool": call.name,
            "call_id": call.id,
            "summary": summarise_call(call.name, call.arguments),
            "args": call.arguments,
        }
        record = self.db.create_approval(
            self.conversation_id,
            {"id": approval_id, "action": action, "reason": reason, "created_at": utcnow()},
        )
        self.db.update_conversation(self.conversation_id, status="waiting_approval")
        self.emit("approval_required", approval={**record, "conversation_id": self.conversation_id})
        try:
            while not waiter.wait(timeout=0.2):
                if self._stop.is_set():
                    self.db.decide_approval(approval_id, False)
                    self.emit("approval_resolved", approval_id=approval_id, approved=False)
                    return None
            decision = self.db.get_approval_decision(approval_id)
        finally:
            with self._approvals_lock:
                self._approvals.pop(approval_id, None)
        approved = decision == "approved"
        self.db.update_conversation(self.conversation_id, status="running")
        self.emit("approval_resolved", approval_id=approval_id, approved=approved)
        return approved

    def _drain_queue(self) -> list[dict[str, Any]]:
        with self._queue_lock:
            items = list(self._queue)
            self._queue.clear()
        return items


def _describe_attachments(attachments: list[dict[str, Any]]) -> str:
    lines = []
    for att in attachments:
        name = att.get("name")
        mime = att.get("mime_type")
        if mime and mime.startswith("image/"):
            lines.append(f"\n[attached image: {name}]")
        else:
            data = att.get("data") or ""
            lines.append(f"\n[attached file: {name}]\n{data[:20000]}")
    return "".join(lines)
