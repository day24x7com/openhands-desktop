/**
 * Typed client for the Python sidecar.
 *
 * The base URL and session token come from `window.openhands` (injected by the
 * Electron preload) when running inside the desktop shell, falling back to Vite
 * env vars for browser-only development.
 */

import type {
  AppSettings,
  ConnectionTestResult,
  Conversation,
  ConversationEvent,
  CreateConversationInput,
  DockerStatus,
  FileContent,
  FileDiff,
  FileNode,
  GitBranches,
  GitOperation,
  GitStatus,
  HealthResponse,
  LlmProfile,
  LlmProfileInput,
  Workspace,
} from '@ohd/shared-types';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export interface SidecarConfig {
  baseUrl: string;
  token: string | null;
}

declare global {
  interface Window {
    openhands?: {
      getSidecarConfig: () => Promise<SidecarConfig>;
      pickDirectory: () => Promise<string | null>;
      openExternal: (url: string) => Promise<void>;
      platform: string;
    };
  }
}

const envBase = (import.meta as unknown as { env?: Record<string, string> }).env ?? {};

let cachedConfig: SidecarConfig | null = null;

export async function resolveConfig(): Promise<SidecarConfig> {
  if (cachedConfig) return cachedConfig;
  if (window.openhands) {
    cachedConfig = await window.openhands.getSidecarConfig();
  } else {
    cachedConfig = {
      baseUrl: envBase.VITE_SIDECAR_URL ?? 'http://127.0.0.1:18080',
      token: envBase.VITE_SIDECAR_TOKEN ?? null,
    };
  }
  return cachedConfig;
}

export function resetSidecarConfig(): void {
  cachedConfig = null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const config = await resolveConfig();
  const headers = new Headers(init.headers);
  if (config.token) headers.set('Authorization', `Bearer ${config.token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');

  let response: Response;
  try {
    response = await fetch(`${config.baseUrl}${path}`, { ...init, headers });
  } catch (error) {
    throw new ApiError(`Cannot reach the agent service. ${(error as Error).message}`, 0);
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const body = text ? safeJson(text) : null;
  if (!response.ok) {
    const apiDetail =
      body && typeof body === 'object' && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : '';
    const detail = apiDetail || text || response.statusText;
    throw new ApiError(detail, response.status);
  }
  return body as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

export const api = {
  /** Shell/UI plumbing needs the raw loopback URL + token (e.g. the terminal socket). */
  getSidecarConfig: () => resolveConfig(),

  // ---------------------------------------------------------------- health
  health: () => request<HealthResponse>('/health'),
  docker: () => request<DockerStatus>('/api/docker/status'),

  // -------------------------------------------------------------- settings
  getSettings: () => request<AppSettings>('/api/settings'),
  saveSettings: (settings: AppSettings) =>
    request<AppSettings>('/api/settings', { method: 'PUT', body: JSON.stringify(settings) }),

  // ---------------------------------------------------------- llm profiles
  listProfiles: () => request<LlmProfile[]>('/api/llm-profiles'),
  createProfile: (input: LlmProfileInput) => request<LlmProfile>('/api/llm-profiles', json(input)),
  updateProfile: (id: string, input: LlmProfileInput) =>
    request<LlmProfile>(`/api/llm-profiles/${id}`, { method: 'PUT', body: JSON.stringify(input) }),
  deleteProfile: (id: string) => request<void>(`/api/llm-profiles/${id}`, { method: 'DELETE' }),
  testProfile: (input: LlmProfileInput) =>
    request<ConnectionTestResult>('/api/llm-profiles/test', json(input)),
  testSavedProfile: (id: string) =>
    request<ConnectionTestResult>(`/api/llm-profiles/${id}/test`, { method: 'POST' }),

  // ------------------------------------------------------------ workspaces
  listWorkspaces: () => request<Workspace[]>('/api/workspaces'),
  createWorkspace: (input: { path: string; kind?: string; name?: string }) =>
    request<Workspace>('/api/workspaces', json(input)),
  cloneWorkspace: (gitUrl: string, target?: string) =>
    request<Workspace>('/api/workspaces/clone', json({ git_url: gitUrl, target })),
  deleteWorkspace: (id: string) => request<void>(`/api/workspaces/${id}`, { method: 'DELETE' }),

  // --------------------------------------------------------- conversations
  listConversations: (search?: string) =>
    request<Conversation[]>(`/api/conversations${search ? `?q=${encodeURIComponent(search)}` : ''}`),
  getConversation: (id: string) => request<Conversation>(`/api/conversations/${id}`),
  createConversation: (input: CreateConversationInput) =>
    request<Conversation>('/api/conversations', json(input)),
  patchConversation: (id: string, patch: { title?: string; pinned?: boolean }) =>
    request<Conversation>(`/api/conversations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteConversation: (id: string) => request<void>(`/api/conversations/${id}`, { method: 'DELETE' }),
  events: (id: string, after = 0) =>
    request<ConversationEvent[]>(`/api/conversations/${id}/events?after=${after}`),
  sendMessage: (id: string, content: string, attachments: unknown[] = []) =>
    request<Conversation>(`/api/conversations/${id}/messages`, json({ content, attachments })),
  run: (id: string) => request<Conversation>(`/api/conversations/${id}/run`, { method: 'POST' }),
  pause: (id: string) => request<Conversation>(`/api/conversations/${id}/pause`, { method: 'POST' }),
  resume: (id: string) => request<Conversation>(`/api/conversations/${id}/resume`, { method: 'POST' }),
  stop: (id: string) => request<Conversation>(`/api/conversations/${id}/stop`, { method: 'POST' }),
  approve: (id: string, approval_id: string, approved: boolean, remember = false) =>
    request<Conversation>(
      `/api/conversations/${id}/approval`,
      json({ approval_id: approval_id, approved, remember }),
    ),
  exportUrl: async (id: string, format: 'markdown' | 'json' = 'markdown') => {
    const config = await resolveConfig();
    const token = config.token ? `&token=${encodeURIComponent(config.token)}` : '';
    return `${config.baseUrl}/api/conversations/${id}/export?format=${format}${token}`;
  },

  // ----------------------------------------------------------- workspace io
  files: (id: string, path = '.', depth = 2) =>
    request<FileNode[]>(`/api/conversations/${id}/files?path=${encodeURIComponent(path)}&depth=${depth}`),
  readFile: (id: string, path: string) =>
    request<FileContent>(`/api/conversations/${id}/file?path=${encodeURIComponent(path)}`),
  writeFile: (id: string, path: string, content: string) =>
    request<FileContent>(`/api/conversations/${id}/file?path=${encodeURIComponent(path)}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  diff: (id: string, path?: string) =>
    request<FileDiff[]>(`/api/conversations/${id}/diff${path ? `?path=${encodeURIComponent(path)}` : ''}`),
  git: (id: string) => request<GitStatus>(`/api/conversations/${id}/git`),
  gitInit: (id: string) => request<GitOperation>(`/api/conversations/${id}/git/init`, { method: 'POST' }),
  gitCommit: (id: string, message: string, paths?: string[]) =>
    request<GitOperation>(`/api/conversations/${id}/git/commit`, json({ message, paths })),
  gitBranches: (id: string) => request<GitBranches>(`/api/conversations/${id}/git/branches`),
  gitCheckout: (id: string, branch: string, create = false) =>
    request<GitOperation>(`/api/conversations/${id}/git/checkout`, json({ branch, create })),
  acceptFile: (id: string, path: string) =>
    request<{ ok: boolean; output: string }>(`/api/conversations/${id}/diff/accept`, json({ path })),
  rejectFile: (id: string, path: string) =>
    request<{ ok: boolean; output: string }>(`/api/conversations/${id}/diff/reject`, json({ path })),
  shell: (id: string, command: string, timeout_seconds = 120) =>
    request<{ ok: boolean; output: string; exit_code: number; duration_ms: number }>(
      `/api/conversations/${id}/shell`,
      json({ command, timeout_seconds: timeout_seconds }),
    ),
  uploadAttachment: async (id: string, file: File) => {
    const config = await resolveConfig();
    const form = new FormData();
    form.append('file', file, file.name);
    const headers: Record<string, string> = {};
    if (config.token) headers.Authorization = `Bearer ${config.token}`;
    const response = await fetch(`${config.baseUrl}/api/conversations/${id}/attachments`, {
      method: 'POST',
      body: form,
      headers,
    });
    if (!response.ok) throw new ApiError('Upload failed', response.status);
    return (await response.json()) as {
      id: string;
      name: string;
      mime_type: string;
      data: string;
      size: number;
    };
  },

  // -------------------------------------------------------------- ws stream
  openEventStream: async (conversation_id: string, onMessage: (payload: unknown) => void) => {
    const config = await resolveConfig();
    const wsBase = config.baseUrl.replace(/^http/, 'ws');
    const token = config.token ? `?token=${encodeURIComponent(config.token)}` : '';
    const socket = new WebSocket(`${wsBase}/api/conversations/${conversation_id}/ws${token}`);
    socket.onmessage = (event) => {
      try {
        onMessage(JSON.parse(String(event.data)));
      } catch {
        /* ignore malformed frames */
      }
    };
    return socket;
  },
};
