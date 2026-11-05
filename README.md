# OpenHands Desktop

A native desktop app for the [OpenHands](https://docs.openhands.dev) software-engineering agent.
Install it, paste an API key, and point the agent at your own project folder — no terminal work and
no Docker required (an optional Docker sandbox is supported).

```
┌──────────────────────────── Electron shell ─────────────────────────────┐
│  React UI (Vite + React 18 + Tailwind + xterm.js)                       │
│        │  REST + WebSocket on 127.0.0.1, per-session bearer token       │
│  Python sidecar (FastAPI)                                               │
│        ├── agent loop ── tools ── LLM providers (Anthropic / OpenAI-wire)│
│        ├── local workspace (or optional Docker sandbox)                 │
│        └── SQLite store + encrypted credential vault                    │
└─────────────────────────────────────────────────────────────────────────┘
```

Everything runs locally: the UI only talks to the sidecar on loopback, and API keys never leave the
machine. The shell mints a random session token at every launch, so other local processes cannot
drive your agent.

## What it does

| Feature | Where |
|---|---|
| 4-step onboarding (provider → key + connection test → project folder → confirm) | `apps/ui/src/components/OnboardingWizard.tsx` |
| Chat with streaming timeline, tool calls, plans, cost/token accounting | `Timeline.tsx`, `ChatWorkspace.tsx` |
| File explorer with git markers, editor, diff review with accept/reject | `Panels.tsx` |
| Interactive terminal (real PTY, persistent cwd/env) | `TerminalPanel.tsx` + `sidecar/app/terminal.py` |
| Approval dialog for risky commands | `Panels.tsx`, `sidecar/app/safety.py` |
| Settings, providers, conversation history/export | `SettingsView.tsx`, `sidecar/app/main.py` |

**Models** — Anthropic, OpenAI, Azure OpenAI, Google Gemini, OpenRouter, Bedrock, any
OpenAI-compatible endpoint (Ollama, LM Studio, vLLM), plus an offline `mock` provider for demos.
Keys live in an encrypted vault (DPAPI on Windows, a `0600` file elsewhere) and are never returned by
the API or written to logs.

**Safety** — the agent can only touch paths inside the workspace root, and commands matching a
risky-pattern list (`rm -rf`, `format`, `del /f`, `shutdown`, force-push, …) pause the run and wait
for explicit approval.

## Layout

| Path | Purpose |
|---|---|
| `apps/ui` | React + TypeScript + Vite frontend |
| `apps/shell` | Electron main/preload: sidecar lifecycle, session-token auth, IPC, folder picker |
| `sidecar` | FastAPI service: conversations, agent runtime, tools, LLM profiles, workspaces, terminal |
| `packages/shared-types` | TypeScript contracts for the sidecar API and event stream |
| `scripts` | `setup_dev.py` (dev bootstrap), `bundle_python.py` (embedded runtime for the installer) |
| `docs` | Architecture, API reference, roadmap |

## Run it on your laptop

Requirements: **Python 3.11+**, **Node.js 20+**, and **Git** (for the git panel).

```bash
git clone https://github.com/day24x7com/openhands-desktop.git
cd openhands-desktop
python scripts/setup_dev.py
```

`setup_dev.py` creates `.venv`, installs the Python sidecar into it, runs `npm install`, and executes
the sidecar test suite as a sanity check (expect `63 passed`). You do not need to activate `.venv`
afterwards: the dev scripts find it themselves.

### Option A — run the desktop app (Electron)

```bash
npm run dev:ui      # terminal 1: UI dev server on http://localhost:5173
npm run dev:shell   # terminal 2: Electron window, starts its own sidecar
```

The Electron window needs the Vite server, so keep terminal 1 running. The shell picks a free port
for the sidecar and mints a session token automatically, so nothing else to configure.

### Option B — browser only (no Electron)

```bash
npm run dev:sidecar   # terminal 1: backend on http://127.0.0.1:18080
npm run dev:ui        # terminal 2: open http://localhost:5173
```

In browser mode the UI talks to the sidecar without a token, which is fine for local development.
To use a tokenised sidecar instead, start it with `OHD_SESSION_TOKEN=...` and set
`VITE_SIDECAR_URL` + `VITE_SIDECAR_TOKEN` before running `npm run dev:ui`.

### First run inside the app

1. Pick a provider (Anthropic, OpenAI, Google, OpenRouter, Bedrock, or any OpenAI-compatible
   endpoint such as Ollama) and paste your API key.
2. Optionally set a custom base URL for a local model (LM Studio, vLLM, Ollama).
3. Press **Test connection** — it makes one real request, so it catches wrong keys immediately.
4. Choose a project folder — or click **try the sample project**, which creates a small Python
   project with one deliberately failing test so you can watch the agent fix it.

No key to hand? Choose the **mock** provider: it runs the full agent loop offline with canned
responses, which is enough to exercise the UI, terminal, diffs and git panel.

### Useful commands

```bash
npm run test:all   # sidecar (pytest) + UI (vitest) + shell supervisor tests
npm run lint       # ruff
npm run typecheck  # tsc
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: fastapi` | Run `python scripts/setup_dev.py`; the launcher warns if `.venv` is missing |
| Blank Electron window | The Vite server is not running — start `npm run dev:ui` |
| Port already in use | Stop the other process; the sidecar also accepts `--port` via `scripts/run_sidecar.py` |
| Terminal panel says "PTY unavailable" | `pywinpty` ships with the sidecar for Windows; re-run `python scripts/setup_dev.py` to refresh deps |
| Onboarding never finishes | Provider test failed; check the key, base URL and your network |

## Tests

```bash
npm run test:all    # sidecar (pytest) + UI (vitest) + shell supervisor (node:test)
npm run lint        # ruff
npm run typecheck   # tsc project references
```

Currently: 54 sidecar tests, 10 UI tests, 5 shell integration tests. The shell tests spawn a real
Python sidecar and assert token gating, readiness polling and clean shutdown.

## Building the Windows installer

```bash
python scripts/bundle_python.py   # download and populate an embedded CPython runtime
npm run build:exe                 # NSIS installer in release/
```

The installer is per-user by default and adds desktop and Start-menu shortcuts. Data lives in
`%APPDATA%/OpenHands Desktop`. Pushing a `v*` tag runs `.github/workflows/release.yml`, which builds
the installer on Windows and attaches it to the GitHub release.

## Configuration

| Variable | Used by | Meaning |
|---|---|---|
| `OHD_DATA_DIR` | sidecar | Data directory (defaults to the Electron `userData` folder) |
| `OHD_SESSION_TOKEN` | sidecar | Required bearer token — set automatically by the shell |
| `OHD_MAX_AGENT_STEPS` | sidecar | Agent step ceiling (default 40) |
| `OHD_ALLOW_REMOTE_BIND` | sidecar | Allow binding beyond loopback (off by default) |
| `OHD_SANDBOX_IMAGE` | sidecar | Docker image used when a workspace runs in sandbox mode |
| `OHD_PYTHON` | shell | Interpreter used to run the sidecar in dev |
| `VITE_SIDECAR_URL` / `VITE_SIDECAR_TOKEN` | UI | Point the browser-only UI at an existing sidecar |

## License

MIT
