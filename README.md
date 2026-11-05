# OpenHands Desktop

A native desktop app for the [OpenHands](https://docs.openhands.dev) software-engineering agent.
Install it, paste an API key, and run an AI software engineer on your own machine — no terminal,
no Docker required (Docker/WSL2 sandbox is optional).

```
┌────────────────────────────── Electron shell ───────────────────────────────┐
│  React UI (Vite + React 19 + Tailwind + Monaco/xterm-style panels)           │
│        │ REST + WebSocket (localhost, bearer session token)                  │
│  Python sidecar (FastAPI) ── agent loop ── tools ── LLM (LiteLLM-compatible)  │
│        ├── Local workspace        ├── Docker sandbox      └── SQLite store    │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Layout

| Path | Purpose |
|---|---|
| `apps/ui` | React + TypeScript + Vite frontend (chat, timeline, editor/diff, terminal, plan, settings) |
| `apps/shell` | Electron main/preload: sidecar lifecycle, session-token auth, IPC, workspace pickers |
| `sidecar` | Python FastAPI service: conversations, agent runtime, tools, LLM profiles, workspaces, safety policy |
| `packages/shared-types` | TypeScript contracts for the sidecar API + event stream |
| `installer` | electron-builder / NSIS configuration notes |
| `docs` | Spec, architecture, API reference |

## Quick start (dev)

```bash
# 1) sidecar (Python 3.11+)
cd sidecar
pip install -e ".[dev]"
uvicorn app.main:app --port 18080      # or: python -m app

# 2) UI (Node 20+)
npm install
npm run dev --workspace apps/ui        # http://localhost:5173

# 3) desktop shell (spawns the sidecar for you)
npm run dev --workspace apps/shell
```

The UI talks to the sidecar directly when running standalone (`VITE_SIDECAR_URL`,
`VITE_SIDECAR_TOKEN`). Under the Electron shell, the sidecar URL/token are injected by the preload
script and the bearer token never touches the renderer's persistent storage.

## Features (MVP / P0)

- First-run onboarding wizard: provider → credentials → model → **Test connection** → workspace.
- LLM profiles: Anthropic, OpenAI, Azure, Google, OpenRouter, Bedrock, any OpenAI-compatible
  endpoint, plus local Ollama / LM Studio / vLLM. Per-conversation override.
- Conversations: streaming timeline, thinking/action/observation cards, stop/pause/resume,
  message queue, rename/pin/search/delete, Markdown+JSON export.
- Agent tools: shell (PowerShell/cmd/bash), file editor with str-replace & undo, web fetch,
  task planner, think/finish.
- Safety layer: risky-command approval (approve/deny/regex policy), workspace path guard,
  CRLF preservation, no admin elevation.
- Workspaces: local folder (default) and Docker sandbox (optional), with path translation.
- File explorer + Monaco editor + per-file diff/accept-reject.
- API keys stored encrypted at rest (machine-key cipher; Windows Credential Manager on Windows).

## Docs

- [docs/SPEC.md](docs/SPEC.md) — product spec
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/API.md](docs/API.md)

MIT licensed. OpenHands is a trademark of its respective owners; this is an independent desktop
front-end built on the OpenHands agent SDK surface.
