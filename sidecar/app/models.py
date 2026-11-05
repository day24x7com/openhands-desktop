"""Pydantic models mirroring `packages/shared-types/src/index.ts`.

The sidecar is the single source of truth for the wire format; the TypeScript
package mirrors these definitions for the UI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

WorkspaceKind = Literal["local", "docker", "remote"]
ConversationStatus = Literal["idle", "running", "paused", "waiting_approval", "error", "done"]
LlmProvider = Literal[
    "anthropic",
    "openai",
    "azure",
    "google",
    "openrouter",
    "bedrock",
    "openai-compatible",
    "ollama",
    "lmstudio",
    "vllm",
    "mock",
]
ShellKind = Literal["powershell", "cmd", "bash", "wsl"]


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------- LLM


class LlmProfileInput(ApiModel):
    name: str
    provider: LlmProvider
    model: str
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout_seconds: int = 300
    retries: int = 2
    extra_headers: dict[str, str] = Field(default_factory=dict)
    is_default: bool = False


class LlmProfile(ApiModel):
    id: str
    name: str
    provider: LlmProvider
    model: str
    base_url: str | None
    api_key_ref: str | None
    has_api_key: bool
    temperature: float
    max_tokens: int
    timeout_seconds: int
    retries: int
    extra_headers: dict[str, str]
    is_default: bool
    created_at: str


class ConnectionTestResult(ApiModel):
    ok: bool
    latency_ms: int
    model: str | None = None
    message: str


# --------------------------------------------------------------- workspace


class Workspace(ApiModel):
    id: str
    path: str
    kind: WorkspaceKind
    name: str
    git_remote: str | None = None
    last_opened: str
    container_id: str | None = None


class WorkspaceInput(ApiModel):
    path: str
    kind: WorkspaceKind = "local"
    name: str | None = None
    git_remote: str | None = None


class FileNode(ApiModel):
    name: str
    path: str
    type: Literal["file", "dir"]
    size: int | None = None
    git_status: Literal["M", "A", "D", "?"] | None = None


class FileContent(ApiModel):
    path: str
    content: str
    language: str
    eol: Literal["lf", "crlf"]
    truncated: bool = False


class FileWrite(ApiModel):
    content: str


class DiffHunk(ApiModel):
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[str]


class FileDiff(ApiModel):
    path: str
    status: Literal["added", "modified", "deleted"]
    hunks: list[DiffHunk]
    additions: int
    deletions: int


class GitStatusEntry(ApiModel):
    path: str
    status: Literal["M", "A", "D", "?", "R", "U"]


class GitStatus(ApiModel):
    branch: str | None
    entries: list[GitStatusEntry]
    ahead: int = 0
    behind: int = 0


# ------------------------------------------------------------ conversation


class CreateConversationInput(ApiModel):
    workspace_id: str
    llm_profile_id: str | None = None
    title: str | None = None
    mode: WorkspaceKind | None = None
    shell: ShellKind | None = None
    confirm_risky_actions: bool = True
    system_prompt_suffix: str | None = None


class Conversation(ApiModel):
    id: str
    title: str
    workspace_id: str
    mode: WorkspaceKind
    llm_profile_id: str | None
    status: ConversationStatus
    pinned: bool
    created_at: str
    updated_at: str
    cost_total: float
    tokens_total: int
    pending_approval: dict[str, Any] | None = None
    queued_messages: int = 0


class ConversationPatch(ApiModel):
    title: str | None = None
    pinned: bool | None = None
    llm_profile_id: str | None = None


class Attachment(ApiModel):
    id: str
    name: str
    mime_type: str
    data: str
    size: int


class SendMessageInput(ApiModel):
    content: str
    attachments: list[Attachment] = Field(default_factory=list)


class ApprovalDecision(ApiModel):
    approval_id: str
    approved: bool
    remember: bool = False


# ------------------------------------------------------------------ events


EventType = Literal[
    "message",
    "thinking",
    "action",
    "observation",
    "approval_required",
    "approval_resolved",
    "status",
    "plan",
    "usage",
    "error",
]


class PlanItem(ApiModel):
    title: str
    status: Literal["todo", "in_progress", "done"] = "todo"
    notes: str = ""


class ConversationEvent(ApiModel):
    """Flattened event shape; `type` selects which optional fields apply."""

    id: int = 0
    conversation_id: str
    seq: int = 0
    type: EventType
    ts: str = Field(default_factory=utcnow)
    role: Literal["user", "assistant", "system"] | None = None
    content: str | None = None
    attachments: list[Attachment] | None = None
    tool: str | None = None
    call_id: str | None = None
    summary: str | None = None
    args: dict[str, Any] | None = None
    ok: bool | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    file_path: str | None = None
    status: ConversationStatus | None = None
    detail: str | None = None
    items: list[PlanItem] | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    total_tokens: int | None = None
    total_cost_usd: float | None = None
    model: str | None = None
    message: str | None = None
    recoverable: bool | None = None
    approval: dict[str, Any] | None = None
    approval_id: str | None = None
    approved: bool | None = None
    remember: bool | None = None

    def to_wire(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


# ---------------------------------------------------------------- settings


class AppSettings(ApiModel):
    onboarded: bool = False
    theme: Literal["dark", "light", "system"] = "dark"
    default_shell: ShellKind = "powershell"
    confirm_risky_actions: bool = True
    allow_network_in_shell: bool = True
    max_cost_usd_per_conversation: float | None = None
    telemetry: bool = False
    last_workspace_id: str | None = None
    last_llm_profile_id: str | None = None


class EnvCheck(ApiModel):
    name: str
    available: bool
    version: str | None = None
    hint: str | None = None


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"
    version: str
    sidecar_version: str
    platform: str
    data_dir: str
    environment: list[EnvCheck]


class DockerStatus(ApiModel):
    available: bool
    engine: str | None = None
    images: list[str] = Field(default_factory=list)
    message: str = ""
