# Architecture

OpenHands Desktop is three processes with two trust boundaries.

```
┌────────────────────────────── Electron main ──────────────────────────────┐
│  • owns the sidecar lifecycle (spawn / health / kill)                       │
│  • mints a random 32-byte session token per launch                          │
│  • exposes a narrow IPC bridge (config, folder picker, open external)      │
└───────────────┬────────────────────────────────────────┬───────────────────┘
                │ IPC (contextBridge)                    │ spawn + env
┌───────────────▼────────────────┐          ┌────────────▼──────────────────┐
│ Renderer (React, sandboxed)    │  HTTP/WS │ Sidecar (Python, FastAPI)     │
│ no node, no ipcRenderer        │ ────────▶│ 127.0.0.1:<random port>        │
│ bearer token on every call     │          │ bearer token enforced         │
└────────────────────────────────┘          └────────────┬──────────────────┘
                                                          │
                                        ┌─────────────────▼─────────────────┐
                                        │ workspace (local dir / container) │
                                        └───────────────────────────────────┘
```

## Trust boundaries

**Renderer → shell.** The renderer is a normal web page: `contextIsolation: true`,
`nodeIntegration: false`, navigation and `window.open` are pinned to the app origin, and only the
functions listed in `apps/shell/src/preload.ts` exist on `window.openhands`.

**Renderer → sidecar.** The sidecar listens on loopback only, on a port picked at launch. Every
request needs `Authorization: Bearer <session token>`; `/health` is the single exception so the shell
can poll for readiness before the UI loads. The token comes back through IPC, never through a file
or an environment variable the renderer can read. WebSocket routes take the token as a query
parameter because browsers cannot set headers on a socket handshake.

**Agent → filesystem.** Every path the agent or the UI supplies is resolved against the workspace
root (`sidecar/app/safety.py`, `resolve_in_workspace`). Traversal, absolute paths outside the root and
symlink escapes are rejected before any I/O happens.

## Lifecycle

1. `app.whenReady()` → `Sidecar.start()`.
2. Pick a free port (`listen(0)` then close), generate the token, spawn
   `python -m uvicorn app.main:app --host 127.0.0.1 --port <port>` with `OHD_DATA_DIR`,
   `OHD_SESSION_TOKEN` and `OHD_DESKTOP=1`.
3. Poll `GET /health` every 250 ms until it answers or the 60 s deadline passes. Startup failure
   shows a dialog with the log path instead of a blank window.
4. Create the `BrowserWindow` and load the UI. Sidecar stdout/stderr are piped to
   `<userData>/logs/sidecar.log`.
5. `before-quit` awaits `Sidecar.stop()` (SIGTERM, then SIGKILL after 5 s) so no orphaned Python
   process survives. A crash mid-session raises `sidecar:exited` to the renderer.

On the Python side, `lifespan` shutdown stops all agent runtimes, closes every PTY session and closes
the SQLite connection.

## Sidecar internals

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app, auth middleware, all REST/WS routes, `AppState` (DB, runtimes, terminals, settings) |
| `agent.py` | `AgentRuntime`: the multi-step loop, event streaming, pause/resume/stop, approvals, cost accounting |
| `llm.py` | Provider registry and clients: Anthropic messages API, OpenAI-compatible chat completions, `MockLLM` |
| `tools.py` | Tool definitions and dispatch (shell, read/write/replace file, list, fetch, plan, finish) |
| `safety.py` | Path guard + risky-command patterns |
| `workspace.py` | Local and Docker workspaces, file tree, git status/diff, language guessing |
| `terminal.py` | PTY sessions: ConPTY (Windows) or `pty.fork` (POSIX), behind `TerminalSession` |
| `secrets.py` | Credential vault: DPAPI on Windows, `0600` JSON elsewhere |
| `db.py` | SQLite schema and queries (workspaces, conversations, events, profiles, settings) |
| `config.py` | Settings from environment + data-directory plumbing |

### Event stream

The agent emits typed events (`assistant_message`, `tool_call`, `tool_result`, `approval_request`,
`plan`, `error`, `finished`, …) into a per-conversation runtime. `GET /api/conversations/{id}/ws`
sends a snapshot (conversation + full history) and then live events; the client reconnects with
backoff and refetches if it sees a gap. Events are also persisted, so the timeline survives restarts.

## Failure modes and how they're handled

| Failure | Behaviour |
|---|---|
| Port already in use | A free port is picked per launch, so this cannot happen by accident |
| Python missing / slow start | Health poll times out at 60 s, error dialog names the log file |
| Sidecar crash | `sidecar:exited` reaches the UI, which offers a restart |
| LLM 429 / 5xx | Retried with backoff inside `llm.py`, then surfaced as an `error` event |
| Risky command | Run pauses; nothing executes until the user approves |
| Shell exit in terminal | `exit` frame, panel shows "process exited" and offers *Restart shell* |
| App killed | `before-quit` awaits sidecar termination; PTY child processes get SIGHUP |

## Design notes

* **snake_case on the wire.** Python models and `packages/shared-types` agree on `snake_case`; only
  the local IPC config object is camelCase, since it never crosses the Python boundary.
* **No shell strings in the tool layer.** Commands run through `subprocess` with an argv list built per
  shell (`powershell`, `cmd`, `bash`, `wsl`), never `shell=True`.
* **One terminal implementation, two backends.** `create_session` picks ConPTY or `pty.fork`, so the
  WebSocket handler and the UI are platform-agnostic.
