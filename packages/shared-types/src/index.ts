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
  baseUrl: string | null;
  apiKeyRef: string | null;
  hasApiKey: boolean;
  temperature: number;
  maxTokens: number;
  timeoutSeconds: number;
  retries: number;
  extraHeaders: Record<string, string>;
  isDefault: boolean;
  createdAt: string;
}

export interface LlmProfileInput {
  name: string;
  provider: LlmProvider;
  model: string;
  baseUrl?: string | null;
  apiKey?: string | null;
  temperature?: number;
  maxTokens?: number;
  timeoutSeconds?: number;
  retries?: number;
  extraHeaders?: Record<string, string>;
  isDefault?: boolean;
}

export interface ConnectionTestResult {
  ok: boolean;
  latencyMs: number;
  model: string | null;
  message: string;
}

export interface Workspace {
  id: string;
  path: string;
  kind: WorkspaceKind;
  name: string;
  gitRemote: string | null;
  lastOpened: string;
  /** Container name when kind === 'docker'. */
  containerId?: string | null;
}

export interface Conversation {
  id: string;
  title: string;
  workspaceId: string;
  mode: WorkspaceKind;
  llmProfileId: string | null;
  status: ConversationStatus;
  pinned: boolean;
  createdAt: string;
  updatedAt: string;
  costTotal: number;
  tokensTotal: number;
  pendingApproval: ApprovalRequest | null;
  queuedMessages: number;
}

export interface CreateConversationInput {
  workspaceId: string;
  llmProfileId?: string | null;
  title?: string;
  /** Overrides the workspace kind for this conversation (cannot change later). */
  mode?: WorkspaceKind;
  shell?: ShellKind;
  confirmRiskyActions?: boolean;
  systemPromptSuffix?: string;
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
  conversationId: string;
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
  callId: string;
  /** Human readable one-liner for the timeline card. */
  summary: string;
  args: Record<string, unknown>;
}

export interface ObservationEvent extends BaseEvent {
  type: 'observation';
  tool: string;
  callId: string;
  ok: boolean;
  content: string;
  exitCode?: number | null;
  durationMs?: number;
  /** Set for file-editing tools so the UI can open a diff. */
  filePath?: string | null;
}

export interface UsageEvent extends BaseEvent {
  type: 'usage';
  promptTokens: number;
  completionTokens: number;
  costUsd: number;
  totalTokens: number;
  totalCostUsd: number;
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
  conversationId: string;
  action: ActionEvent | null;
  reason: string;
  createdAt: string;
}

export interface ApprovalRequiredEvent extends BaseEvent {
  type: 'approval_required';
  approval: ApprovalRequest;
}

export interface ApprovalResolvedEvent extends BaseEvent {
  type: 'approval_resolved';
  approvalId: string;
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
  | { kind: 'subscribe'; conversationId: string };

/* ---------------------------------------------------------------- content */

export interface Attachment {
  id: string;
  name: string;
  mimeType: string;
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
  gitStatus?: 'M' | 'A' | 'D' | '?' | null;
}

export interface FileContent {
  path: string;
  content: string;
  language: string;
  eol: 'lf' | 'crlf';
  truncated: boolean;
}

export interface DiffHunk {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
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
  defaultShell: ShellKind;
  confirmRiskyActions: boolean;
  allowNetworkInShell: boolean;
  maxCostUsdPerConversation: number | null;
  telemetry: boolean;
  lastWorkspaceId: string | null;
  lastLlmProfileId: string | null;
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
  sidecarVersion: string;
  platform: string;
  dataDir: string;
  environment: EnvCheck[];
}

export interface DockerStatus {
  available: boolean;
  engine: string | null;
  images: string[];
  message: string;
}
