/**
 * Contracts shared by the desktop UI (`apps/ui`), the Electron shell (`apps/shell`)
 * and the Python sidecar (`sidecar/app`). Keep this file in sync with
 * `sidecar/app/models.py` — both describe the same wire format.
 */

export type WorkspaceKind = 'local' | 'docker' | 'remote';
export type ConversationStatus = 'idle' | 'running' | 'paused' | 'waiting_approval' | 'error' | 'done';
export type LlmProvider =
  | 'anthropic'
  | 'openai'
  | 'azure'
  | 'google'
  | 'openrouter'
  | 'bedrock'
  | 'openai-compatible'
  | 'ollama'
  | 'lmstudio'
  | 'vllm'
  | 'mock';

export type ShellKind = 'powershell' | 'cmd' | 'bash' | 'wsl';

/** An LLM profile. API keys are never returned by the API — only the credential name. */
export interface LlmProfile {
  id: string;
  name: string;
  provider: LlmProvider;
  model: string;
  base_url: string | null;
  api_key_ref: string | null;
  has_api_key: boolean;
  temperature: number;
  max_tokens: number;
  timeout_seconds: number;
  retries: number;
  extra_headers: Record<string, string>;
  is_default: boolean;
  created_at: string;
}

export interface LlmProfileInput {
  name: string;
  provider: LlmProvider;
  model: string;
  base_url?: string | null;
  api_key?: string | null;
  temperature?: number;
  max_tokens?: number;
  timeout_seconds?: number;
  retries?: number;
  extra_headers?: Record<string, string>;
  is_default?: boolean;
}

export interface ConnectionTestResult {
  ok: boolean;
  latency_ms: number;
  model: string | null;
  message: string;
}

export interface Workspace {
  id: string;
  path: string;
  kind: WorkspaceKind;
  name: string;
  git_remote: string | null;
  last_opened: string;
  /** Container name when kind === 'docker'. */
  container_id?: string | null;
}

export interface Conversation {
  id: string;
  title: string;
  workspace_id: string;
  mode: WorkspaceKind;
  llm_profile_id: string | null;
  status: ConversationStatus;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  cost_total: number;
  tokens_total: number;
  pending_approval: ApprovalRequest | null;
  queued_messages: number;
}

export interface CreateConversationInput {
  workspace_id: string;
  llm_profile_id?: string | null;
  title?: string;
  /** Overrides the workspace kind for this conversation (cannot change later). */
  mode?: WorkspaceKind;
  shell?: ShellKind;
  confirm_risky_actions?: boolean;
  system_prompt_suffix?: string;
}

/* ------------------------------------------------------------------ events */

export type EventType =
  | 'message'
  | 'thinking'
  | 'action'
  | 'observation'
  | 'approval_required'
  | 'approval_resolved'
  | 'status'
  | 'plan'
  | 'usage'
  | 'error';

export interface BaseEvent {
  id: number;
  conversation_id: string;
  seq: number;
  ts: string;
}

export interface MessageEvent extends BaseEvent {
  type: 'message';
  role: 'user' | 'assistant' | 'system';
  content: string;
  attachments?: Attachment[];
}

/** One entry of the agent's todo plan. */
export interface PlanItem {
  title: string;
  status: 'todo' | 'in_progress' | 'done';
  notes?: string;
}

export interface ThinkingEvent extends BaseEvent {
  type: 'thinking';
  content: string;
}

export interface ActionEvent extends BaseEvent {
  type: 'action';
  tool: string;
  call_id: string;
  /** Human readable one-liner for the timeline card. */
  summary: string;
  args: Record<string, unknown>;
}

export interface ObservationEvent extends BaseEvent {
  type: 'observation';
  tool: string;
  call_id: string;
  ok: boolean;
  content: string;
  exit_code?: number | null;
  duration_ms?: number;
  /** Set for file-editing tools so the UI can open a diff. */
  file_path?: string | null;
}

export interface UsageEvent extends BaseEvent {
  type: 'usage';
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  total_tokens: number;
  total_cost_usd: number;
  model: string;
}

export interface StatusEvent extends BaseEvent {
  type: 'status';
  status: ConversationStatus;
  detail?: string;
}

export interface PlanEvent extends BaseEvent {
  type: 'plan';
  items: PlanItem[];
}

export interface ErrorEvent extends BaseEvent {
  type: 'error';
  message: string;
  recoverable: boolean;
}

export interface ApprovalRequest {
  id: string;
  conversation_id: string;
  action: ActionEvent | null;
  reason: string;
  created_at: string;
}

export interface ApprovalRequiredEvent extends BaseEvent {
  type: 'approval_required';
  approval: ApprovalRequest;
}

export interface ApprovalResolvedEvent extends BaseEvent {
  type: 'approval_resolved';
  approval_id: string;
  approved: boolean;
  remember?: boolean;
}

export type ConversationEvent =
  | MessageEvent
  | ThinkingEvent
  | ActionEvent
  | ObservationEvent
  | UsageEvent
  | StatusEvent
  | PlanEvent
  | ErrorEvent
  | ApprovalRequiredEvent
  | ApprovalResolvedEvent;

/** Envelope pushed over the WebSocket. */
export type WsServerMessage =
  | { kind: 'event'; event: ConversationEvent }
  | { kind: 'snapshot'; conversation: Conversation; events: ConversationEvent[] }
  | { kind: 'pong' };

export type WsClientMessage =
  | { kind: 'ping' }
  | { kind: 'subscribe'; conversation_id: string };

/* ---------------------------------------------------------------- content */

export interface Attachment {
  id: string;
  name: string;
  mime_type: string;
  /** base64 for images / text content for text files. */
  data: string;
  size: number;
}

/* --------------------------------------------------------------- workspace */

export interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'dir';
  size?: number;
  /** git status letter: 'M' | 'A' | 'D' | '?' | null */
  git_status?: 'M' | 'A' | 'D' | '?' | null;
}

export interface FileContent {
  path: string;
  content: string;
  language: string;
  eol: 'lf' | 'crlf';
  truncated: boolean;
}

export interface DiffHunk {
  old_start: number;
  old_lines: number;
  new_start: number;
  new_lines: number;
  lines: string[];
}

export interface FileDiff {
  path: string;
  status: 'added' | 'modified' | 'deleted';
  hunks: DiffHunk[];
  additions: number;
  deletions: number;
}

export interface GitStatusEntry {
  path: string;
  status: 'M' | 'A' | 'D' | '?' | 'R' | 'U';
}

export interface GitStatus {
  branch: string | null;
  entries: GitStatusEntry[];
  ahead: number;
  behind: number;
}

/* ---------------------------------------------------------------- settings */

export interface AppSettings {
  onboarded: boolean;
  theme: 'dark' | 'light' | 'system';
  default_shell: ShellKind;
  confirm_risky_actions: boolean;
  allow_network_in_shell: boolean;
  max_cost_usd_per_conversation: number | null;
  telemetry: boolean;
  last_workspace_id: string | null;
  last_llm_profile_id: string | null;
}

/* ------------------------------------------------------------------ health */

export interface EnvCheck {
  name: string;
  available: boolean;
  version: string | null;
  hint: string | null;
}

export interface HealthResponse {
  status: 'ok';
  version: string;
  sidecar_version: string;
  platform: string;
  data_dir: string;
  environment: EnvCheck[];
}

export interface DockerStatus {
  available: boolean;
  engine: string | null;
  images: string[];
  message: string;
}
