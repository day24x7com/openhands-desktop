# API reference

Base URL: `http://127.0.0.1:<port>` (chosen at launch). All routes except `/health` require
`Authorization: Bearer <session token>` and answer `401` with
`{"detail": "invalid or missing session token"}` otherwise.

Errors use FastAPI's shape: `{"detail": "..."}` with `400` (bad input), `404` (missing resource) or
`409` (conflict, e.g. deleting a workspace that still has conversations).

## Health

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Unauthenticated. `{status, version, sidecar_version, uptime_s}` — used by the shell readiness poll |
| GET | `/api/health` | Same payload, authenticated |

## Environment & settings

| Method | Path | Notes |
|---|---|---|
| GET | `/api/docker/status` | `{available, version, error}` |
| GET | `/api/settings` | `{onboarded, theme, default_shell, ...}` |
| PUT | `/api/settings` | Merge-updates settings |

## LLM profiles

| Method | Path | Notes |
|---|---|---|
| GET | `/api/llm-profiles` | Public view: never includes the API key |
| POST | `/api/llm-profiles` | `{name, provider, model, base_url?, api_key?, temperature?, max_tokens?, is_default?}` |
| PUT | `/api/llm-profiles/{id}` | Partial update; omitting `api_key` keeps the stored key |
| DELETE | `/api/llm-profiles/{id}` | |
| POST | `/api/llm-profiles/test` | Test an unsaved profile: `{provider, model, base_url?, api_key?}` → `{ok, message, latency_ms}` |
| POST | `/api/llm-profiles/{id}/test` | Test a saved profile |

Providers: `anthropic`, `openai`, `azure`, `google`, `openrouter`, `bedrock`, `openai-compatible`,
`ollama`, `lmstudio`, `vllm`, `mock`.

## Workspaces

| Method | Path | Notes |
|---|---|---|
| GET | `/api/workspaces` | |
| POST | `/api/workspaces` | `{path, name?, kind?: "local" \| "docker"}` |
| POST | `/api/workspaces/clone` | `{git_url, target?}` — git clone; `400` on failure |
| POST | `/api/workspaces/sample` | Create the onboarding sample project (fails one test until fixed) |
| DELETE | `/api/workspaces/{id}` | `409` if conversations still reference it |

## Conversations

| Method | Path | Notes |
|---|---|---|
| GET | `/api/conversations` | Newest first |
| POST | `/api/conversations` | `{workspace_id, mode?: "local" \| "docker"}` |
| GET | `/api/conversations/{id}` | |
| PATCH | `/api/conversations/{id}` | `{title?, pinned?}` |
| DELETE | `/api/conversations/{id}` | |
| GET | `/api/conversations/{id}/events` | Full persisted event history |
| GET | `/api/conversations/{id}/export` | `?format=markdown\|json` |

## Running the agent

| Method | Path | Notes |
|---|---|---|
| POST | `/api/conversations/{id}/messages` | `{content}` — queue a user message and start the loop if idle |
| POST | `/api/conversations/{id}/run` | Start/resume the loop |
| POST | `/api/conversations/{id}/pause` | Pause after the current step |
| POST | `/api/conversations/{id}/resume` | |
| POST | `/api/conversations/{id}/stop` | Abort the run |
| POST | `/api/conversations/{id}/approval` | `{approval_id, approved, remember?}` — answer a `approval_request` event |

## Files, diffs, git

| Method | Path | Notes |
|---|---|---|
| GET | `/api/conversations/{id}/files` | File tree with git status per path |
| GET | `/api/conversations/{id}/file?path=` | `{path, content, language, truncated, size}` |
| PUT | `/api/conversations/{id}/file` | `{path, content}` — write inside the workspace |
| GET | `/api/conversations/{id}/diff?path=` | Structured hunks: `{path, hunks: [{old_start, old_lines, new_start, new_lines, lines: [{kind, text}]}]}` |
| POST | `/api/conversations/{id}/diff/accept` | Apply the agent's pending change |
| POST | `/api/conversations/{id}/diff/reject` | Roll the file back |
| GET | `/api/conversations/{id}/git` | `{branch, ahead, behind, entries: [{path, status, ...}]}` |
| POST | `/api/conversations/{id}/git/init` | Create a repository in the workspace → `{ok, output, status}` |
| POST | `/api/conversations/{id}/git/commit` | `{message, paths?}` — stages `-A` or the given paths, then commits |
| GET | `/api/conversations/{id}/git/branches` | `{current, branches: [...]}` |
| POST | `/api/conversations/{id}/git/checkout` | `{branch, create?}` — switch or create a branch |

## Shell and attachments

| Method | Path | Notes |
|---|---|---|
| POST | `/api/conversations/{id}/shell` | `{command, timeout_s?}` — one-shot run, `{ok, output, exit_code, duration_ms, truncated}` |
| POST | `/api/conversations/{id}/attachments` | Multipart upload (≤5 MB) → `{id, name, mime_type, size, data}` with base64 `data`; `413` when over the limit |

Attachments passed to `POST /messages` are inlined for the model: text files are decoded and added
to the prompt, images are sent as real image blocks (`image_url` parts, translated to Anthropic's
`image` block for that provider).

## WebSockets

### `WS /api/conversations/{id}/ws?token=...`

Conversation event stream.

Server → client:

```jsonc
{"kind": "snapshot", "conversation": {...}, "events": [...]}  // immediately after connect
{"kind": "event", "event": {"type": "tool_call", ...}}         // live agent events
{"kind": "pong"}                                               // every 20 s while idle
```

Close codes: `4401` bad token, `4404` unknown conversation.

### `WS /api/conversations/{id}/terminal?token=&cols=&rows=&shell=`

Interactive PTY rooted at the workspace directory.

Client → server:

```jsonc
{"kind": "input",  "data": "ls\n"}
{"kind": "resize", "cols": 120, "rows": 40}
{"kind": "close"}
```

Server → client:

```jsonc
{"kind": "output", "data": "raw bytes decoded as UTF-8 (escape sequences preserved)"}
{"kind": "exit"}                                  // shell process ended
{"kind": "error", "message": "..."}               // PTY could not start (e.g. pywinpty missing)
{"kind": "ping"}                                  // every 15 s while idle
```

Close codes: `4401` bad token, `4404` unknown conversation, `1011` PTY unavailable.
