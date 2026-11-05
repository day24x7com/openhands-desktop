# SPEC: OpenHands Desktop for Windows

**Version:** 0.1 (Draft)
**Date:** 05 Nov 2026
**Goal:** OpenHands ki *full functionality* ek native Windows desktop app me dena: install karo, API key daalo, aur AI software engineer agent chalao, bina terminal/Docker ki tension ke.

---

## 1. Overview

### 1.1 Problem
OpenHands (open-source AI software-engineering agent, MIT license) abhi mainly Docker + browser UI, CLI, ya Python SDK se chalta hai. Windows users ke liye setup mushkil hai (Docker Desktop, WSL2, ports, env vars).

### 1.2 Solution
Ek single-installer Windows app jo:
- Agent engine (OpenHands Software Agent SDK / agent-server) ko bundle ya auto-manage kare
- Chat + code editor + terminal + browser + file explorer ek hi window me de
- Local (no Docker) aur Docker/WSL2 sandbox dono support kare
- Kisi bhi LLM provider (cloud ya local) ke saath chale

### 1.3 Non-Goals (v1)
- OpenHands Cloud ke hosted features (Slack/Jira/Linear hosted integrations) ka clone
- Multi-tenant / enterprise RBAC server
- macOS/Linux builds (architecture cross-platform rakhna hai, par v1 release sirf Windows)

### 1.4 Reference Upstream
- Core: `OpenHands/software-agent-sdk` (packages: `openhands-sdk`, `openhands-tools`, `openhands-workspace`, `openhands-agent-server`)
- CLI: `OpenHands/OpenHands-CLI`
- Docs: https://docs.openhands.dev
- **Note:** V0 architecture deprecated (April 2026). App **V1 SDK** par bane. Implementation se pehle upstream docs/versions dobara verify karo, kyunki API tezi se change ho rahi hai.

---

## 2. Target Users & Personas

| Persona | Need |
|---|---|
| Solo developer | Bina Docker ke local project par agent chalana |
| Student / beginner | One-click install, simple UI |
| Power user | Docker/WSL2 sandbox, custom MCP, multiple agents |
| Privacy-focused | Fully local LLM (Ollama / vLLM / LM Studio), zero cloud |
| Team dev | GitHub/GitLab PR workflow, CI integration |

---

## 3. System Requirements

- **OS:** Windows 10 (21H2+) / Windows 11, x64 (ARM64 stretch goal)
- **RAM:** min 8 GB (16 GB recommended, Docker mode ke liye)
- **Disk:** ~1.5 GB app + runtime, sandbox images alag
- **Optional:** WSL2, Docker Desktop, GPU (local models ke liye)
- **Network:** LLM API ke liye internet (local model mode me optional)

---

## 4. High-Level Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  Windows Desktop App (Shell)             │
│   Tauri/Electron + React UI (Chat, Editor, Term, Browser)│
└───────────────▲───────────────────────────┬──────────────┘
                │ REST + WebSocket          │ IPC (spawn/manage)
                │ (localhost, token auth)   ▼
┌───────────────┴──────────────────────────────────────────┐
│        Agent Service (Python sidecar, bundled)           │
│  openhands-agent-server  +  openhands-sdk  +  tools      │
│  LLM layer (LiteLLM) | Event stream | Conversation store │
└───────┬───────────────┬───────────────────┬──────────────┘
        │               │                   │
 ┌──────▼─────┐  ┌──────▼───────┐   ┌───────▼────────┐
 │ Local      │  │ Docker/WSL2  │   │ Remote Runtime │
 │ Workspace  │  │ Sandbox      │   │ (SSH/K8s/HTTP) │
 └────────────┘  └──────────────┘   └────────────────┘
```

### 4.1 Tech Stack (Recommended)

| Layer | Choice | Reason |
|---|---|---|
| Desktop shell | **Tauri 2** (Rust) ya **Electron** | Tauri = chhota binary; Electron = easier Node ecosystem. Decision: Electron agar node-pty/Monaco integration fast chahiye |
| Frontend | React + TypeScript + Vite + Tailwind | Upstream GUI bhi React hai, components reuse ho sakte hain |
| Code editor | Monaco Editor | VS Code jaisa experience, diff view |
| Terminal | xterm.js + ConPTY (node-pty / portable-pty) | Windows native pseudo-terminal |
| Agent engine | Python 3.12 embedded + `openhands-agent-server` | Upstream compatibility |
| Python packaging | `uv` + PyInstaller / embedded CPython | Offline-friendly installer |
| LLM | LiteLLM via SDK | 100+ providers |
| Storage | SQLite (app data) + JSONL event logs | Simple, portable |
| Secrets | Windows Credential Manager (DPAPI) | API keys plain text me nahi |
| Installer | MSI / NSIS + optional MSIX | Auto-update ke saath |

### 4.2 Process Model
1. App start → Shell sidecar spawn karta hai (random free port, per-session auth token).
2. UI sidecar se localhost par REST/WebSocket se baat karta hai.
3. Har conversation ek workspace se bandha hota hai (local folder ya sandbox container).
4. App close → sidecar graceful shutdown, running agents pause/save.

---

## 5. Functional Requirements

Priority: **P0** = MVP, **P1** = v1.0, **P2** = baad me.

### 5.1 Onboarding & Setup (P0)
- FR-1.1: First-run wizard: LLM provider choose → API key/base URL → model select → test connection.
- FR-1.2: Environment detection: Docker, WSL2, Git, Node, Python; missing ho to guided install links.
- FR-1.3: Default mode "Local Workspace" (no Docker needed).
- FR-1.4: Sample project / demo task ek click me.

### 5.2 LLM Configuration (P0)
- FR-2.1: Providers: Anthropic, OpenAI, Google, Azure OpenAI, OpenRouter, AWS Bedrock, custom OpenAI-compatible endpoint.
- FR-2.2: Local models: Ollama, LM Studio, vLLM (base URL + model name).
- FR-2.3: Advanced settings: temperature, max tokens, timeout, retries, custom headers.
- FR-2.4: Per-conversation model override.
- FR-2.5 (P1): Multiple LLM profiles + condenser model alag (cheap model for summarising).
- FR-2.6 (P1): Cost/token tracker per conversation aur monthly budget limit with hard stop.

### 5.3 Conversations / Chat (P0)
- FR-3.1: Naya conversation, resume, rename, delete, search, pin.
- FR-3.2: Streaming responses, agent "thinking" aur action steps timeline.
- FR-3.3: Stop / Pause / Resume agent kabhi bhi.
- FR-3.4: File/image attach (drag & drop), paste screenshot.
- FR-3.5: Message queue: agent chal raha ho tab bhi user next instruction bhej sake.
- FR-3.6: Conversation export (Markdown / JSON) aur import.
- FR-3.7 (P1): Conversation fork/branch.
- FR-3.8 (P1): Conversation history condensation (long context handle).

### 5.4 Agent Actions (Tools) (P0)
Agent ko ye tools milne chahiye (SDK presets ke mutual):

| Tool | Description | UI surface |
|---|---|---|
| Bash/Terminal | Shell commands (PowerShell / cmd / WSL bash) | Terminal panel |
| File editor | View, create, str-replace edit, undo | Editor + diff |
| Browser | Web navigate, click, type, screenshot | Browser panel |
| Web search/fetch | Docs/web info | Timeline |
| Task tracker/planner | Todo plan visible | Plan sidebar |
| Think / Finish | Reasoning, task completion | Timeline |
| MCP tools | External tool servers | Tools panel |
| Delegate/Sub-agents (P1) | Parallel multi-agent | Agents tab |

- FR-4.1: Har action UI me card ke roop me: command, output, exit code, duration.
- FR-4.2: Windows shell choice: PowerShell (default), cmd, Git Bash, WSL distro.
- FR-4.3: Long-running process (dev server) background me manage hon; UI se kill.

### 5.5 Workspace & Sandbox (P0)
Teen modes:

1. **Local Workspace (default):** agent seedha user ke folder me chalta hai. Fast, par risky, isliye safety layer (sec. 7) mandatory.
2. **Docker Sandbox (P0):** Docker Desktop/WSL2 backend; project folder mount; container per conversation; version-matched runtime image.
3. **Remote Workspace (P1):** SSH / Kubernetes / custom HTTP runtime.

- FR-5.1: Workspace picker (folder browse, recent, Git clone URL se).
- FR-5.2: Per-conversation mode selector, mid-conversation badal nahi sakte (warning dikhao).
- FR-5.3: Docker health check, image pull progress, auto-cleanup of stopped containers.
- FR-5.4: Windows path translation (`C:\` ↔ `/mnt/c` ↔ container path) transparent ho.
- FR-5.5: Port forwarding: agent ka dev server (localhost:3000 etc.) app ke browser panel me preview ho.
- FR-5.6 (P1): KVM/hardware accelerated sandbox (Hyper-V/WSL2 par jahan supported).

### 5.6 Code Editor & File Explorer (P0)
- FR-6.1: File tree with Git status indicators.
- FR-6.2: Monaco editor, syntax highlight, user manual edit bhi kar sake.
- FR-6.3: Agent ke changes ka inline diff, accept/reject per-file ya per-hunk.
- FR-6.4: Changes tab: sab modified files ka summary.
- FR-6.5 (P1): Checkpoints/rollback: har agent run se pehle snapshot (git stash/shadow commit).
- FR-6.6 (P1): "Open in VS Code / Cursor" button.

### 5.7 Integrated Terminal (P0)
- FR-7.1: User ka apna interactive terminal (xterm.js + ConPTY), tabs.
- FR-7.2: Agent terminal read-only mirror, takeover option.

### 5.8 Browser Panel (P1)
- FR-8.1: Embedded Chromium (WebView2) jisme agent ka browser session dikhe.
- FR-8.2: User takeover (login, captcha).
- FR-8.3: Screenshots timeline me.

### 5.9 Git & Integrations (P0/P1)
- FR-9.1 (P0): Git init/status/commit/branch/diff UI.
- FR-9.2 (P1): GitHub / GitLab / Bitbucket OAuth ya PAT login (Credential Manager me).
- FR-9.3 (P1): Repo select → clone → agent branch banaye → PR create ek click me.
- FR-9.4 (P1): Issue URL paste karo, agent resolve kare.
- FR-9.5 (P1): PR review mode (agent diff review kare, comments likhe).
- FR-9.6 (P2): Jira, Linear, Slack, CI/CD hooks.

### 5.10 MCP (Model Context Protocol) (P1)
- FR-10.1: MCP servers add/remove (stdio, SSE, streamable-HTTP).
- FR-10.2: Per-server enable/disable, tool allow-list.
- FR-10.3: Prebuilt catalog (filesystem, fetch, GitHub, etc.).

### 5.11 Skills, Microagents & Memory (P1)
- FR-11.1: Repo-level instructions file support (`AGENTS.md`, `.openhands/` microagents/skills) auto-load.
- FR-11.2: Global + per-repo custom instructions UI.
- FR-11.3: Skill library: enable/disable, create from template.
- FR-11.4: Secrets manager: named secrets agent ko env var ki tarah mile, par logs me masked.

### 5.12 Multi-Agent / Parallel Tasks (P1)
- FR-12.1: Ek saath multiple conversations parallel run (resource-limited, default 3).
- FR-12.2: Sub-agent delegation visualise (tree view).
- FR-12.3: Background tasks queue with notifications.

### 5.13 Automation / Headless (P2)
- FR-13.1: Scheduled tasks (cron-like).
- FR-13.2: Local CLI wrapper `openhands-desktop run "task" --workspace .` jo running app/sidecar use kare.
- FR-13.3: Local API token expose karna (opt-in) taaki doosre tools control kar sakein.

### 5.14 Settings (P0)
- General (theme dark/light/system, language, startup behaviour, telemetry opt-in/out)
- LLM, Sandbox, Shell, Git, MCP, Secrets, Security, Updates, Advanced (env vars, log level)
- Import/Export settings

### 5.15 Notifications & Tray (P1)
- System tray icon, task complete / approval needed Windows toast notification.
- "Minimize to tray" aur agent background me chalta rahe.

### 5.16 Localization (P2)
- English (default), Hindi, aur string-extraction ready (i18n).

---

## 6. Agent Control & Safety (Confirmation Mode)

Windows local mode me safety sabse important hai.

- SR-1: **Confirmation policy** (per conversation):
  - `Always ask` (har action approve)
  - `Ask for risky` (LLM/heuristic risk analyzer; default)
  - `Auto-approve` (sirf sandbox me recommended)
- SR-2: Risk analyzer: destructive patterns (`rm -rf`, `del /s`, `format`, registry edits, `curl | sh`, git force push) → HIGH risk, hamesha approval.
- SR-3: Approval dialog: exact command, working dir, reason, Approve / Deny / Edit / Always-allow-this-pattern.
- SR-4: Path guard: workspace ke bahar read/write block ya approval.
- SR-5: Network egress controls (sandbox mode me allow-list domains).
- SR-6: Secrets redaction in logs/UI/LLM prompts.
- SR-7: Kill switch: global "Stop all agents" hotkey (e.g., `Ctrl+Shift+.`).
- SR-8: Auto-checkpoint before risky operations (FR-6.5).
- SR-9: Prompt-injection awareness: web/page content se aayi instructions ko untrusted mark karo; unke basis par risky action ke liye hamesha approval.

---

## 7. Non-Functional Requirements

| Area | Requirement |
|---|---|
| Performance | App cold start < 4 s; sidecar ready < 8 s; UI 60 fps; event latency < 100 ms |
| Memory | Idle shell+sidecar < 600 MB (sandbox alag) |
| Reliability | Crash recovery: conversation event log se resume; sidecar auto-restart |
| Security | Sidecar sirf `127.0.0.1` par bind, per-session random token, CORS locked |
| Privacy | Default me koi telemetry nahi; opt-in anonymous crash reports |
| Offline | Local LLM ke saath poora offline chale |
| Accessibility | Keyboard navigation, screen-reader labels, high contrast |
| Updates | Signed auto-update (delta), channel: stable/beta |
| Logging | Rotating logs in `%APPDATA%\OpenHandsDesktop\logs`, "Export diagnostics" button |

---

## 8. UI / UX Spec

### 8.1 Main Layout
```
┌─────────────────────────────────────────────────────────────┐
│ Title bar: [Workspace ▾] [Model ▾] [Mode: Local ▾]  ⚙  ─ □ ✕│
├────────┬────────────────────────────┬───────────────────────┤
│Sidebar │  Chat / Agent Timeline     │  Tabs:                │
│        │                            │  Editor | Changes |   │
│ New +  │  user msg                  │  Terminal | Browser | │
│ History│  agent: thinking...        │  Plan | Tools         │
│ Search │  [Action card: bash]       │                       │
│ Repos  │  [Approval needed ⚠]       │                       │
│ Skills │                            │                       │
│ MCP    ├────────────────────────────┤                       │
│        │ [input box + attach + ▶ ]  │                       │
├────────┴────────────────────────────┴───────────────────────┤
│ Status: Agent running • 12 steps • $0.34 • 48k tokens       │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 Key Screens
1. Welcome / Setup wizard
2. Main workspace (above)
3. Settings (sidebar categories)
4. Approval modal
5. Conversation history / search
6. Diff review screen
7. Diagnostics / logs viewer

### 8.3 Shortcuts (default)
| Action | Key |
|---|---|
| New conversation | `Ctrl+N` |
| Command palette | `Ctrl+Shift+P` |
| Toggle terminal | `` Ctrl+` `` |
| Stop agent | `Esc` (focus chat) / `Ctrl+Shift+.` (global) |
| Send message | `Enter` (newline: `Shift+Enter`) |
| Focus chat input | `Ctrl+L` |

---

## 9. Data Model (SQLite, simplified)

```
conversations(id, title, workspace_id, mode, llm_profile_id, status, created_at, updated_at, cost_total, tokens_total)
events(id, conversation_id, seq, type, payload_json, ts)          -- action/observation/message
workspaces(id, path, kind[local|docker|remote], git_remote, last_opened)
llm_profiles(id, name, provider, model, base_url, params_json)    -- API key -> Credential Manager
secrets(id, name, scope)                                           -- value -> Credential Manager
mcp_servers(id, name, transport, command_or_url, enabled, config_json)
skills(id, name, scope[global|repo], path, enabled)
checkpoints(id, conversation_id, workspace_id, ref, ts)
settings(key, value_json)
```

Storage paths:
- `%APPDATA%\OpenHandsDesktop\` → settings, DB, logs
- `%LOCALAPPDATA%\OpenHandsDesktop\runtime\` → bundled Python, sidecar, caches

---

## 10. Sidecar API Contract (Internal)

App UI ↔ sidecar (wraps upstream agent-server; upstream endpoints jahan ho use karo):

| Endpoint | Purpose |
|---|---|
| `POST /conversations` | Naya conversation (workspace, llm, agent config) |
| `GET /conversations/{id}` | State + metadata |
| `POST /conversations/{id}/messages` | User message bhejo |
| `POST /conversations/{id}/run` / `pause` / `stop` | Control |
| `POST /conversations/{id}/confirm` | Approve/deny pending action |
| `WS /conversations/{id}/events` | Live event stream |
| `GET/PUT /settings`, `/llm-profiles`, `/mcp` | Config |
| `GET /workspace/files`, `/workspace/diff` | File tree, diff |
| `GET /health` | Liveness |

Auth: `Authorization: Bearer <session-token>`; token app start par generate, sirf shell ko pata.

---

## 11. Windows-Specific Considerations

1. **Paths:** backslash vs forward slash, long paths (>260), drive letters; normalise sab jagah.
2. **Line endings:** CRLF/LF; `.gitattributes` respect, agent edits me EOL preserve.
3. **Shell:** PowerShell quoting alag; system prompt me current shell batao; WSL bash option.
4. **ConPTY:** Windows 10 1809+ required for terminal.
5. **Docker:** Docker Desktop ya WSL2 me native Docker engine; named pipe `//./pipe/docker_engine` detect.
6. **Permissions/UAC:** Agent ko by-default admin elevation nahi; elevated actions blocked.
7. **Antivirus/SmartScreen:** Code signing certificate (EV preferred) taaki warning na aaye.
8. **Process cleanup:** Job Objects use karo taaki app band hone par child processes orphan na rahein.
9. **Firewall prompt:** Sirf loopback bind → prompt nahi aana chahiye.
10. **File locking:** Windows me open files delete/rename fail hote hain; retries + clear error messages.
11. **WebView2:** Evergreen runtime installer me bundle ya bootstrapper.

---

## 12. Packaging, Distribution & Updates

- Installer: NSIS/MSI, per-user install (no admin) default; per-machine option.
- Bundled: Python runtime, sidecar, `uv`, WebView2 bootstrapper, Git (optional download).
- Auto-update: signed manifests, delta updates, rollback on failed start.
- Portable build (zip) P2.
- Winget / Chocolatey / Microsoft Store listing P2.
- Uninstall: user data rakhne ya delete karne ka option.
- CI/CD: GitHub Actions (windows-latest) → build, test, sign, release.

---

## 13. Testing Strategy

| Level | Tools |
|---|---|
| Unit | Vitest (UI), pytest (sidecar), cargo test (Tauri) |
| Integration | Mock LLM server (recorded responses) + real sidecar |
| E2E | Playwright (WebView2/Electron) full flows |
| Agent evals | SWE-bench-lite subset, internal task suite regression |
| Security | Command-injection, path traversal, prompt-injection test cases |
| Install | Clean Windows 10/11 VMs, with/without Docker/WSL |
| Performance | Startup time, memory, long-run (8h) soak test |

---

## 14. Milestones

| Phase | Scope | Duration (est.) |
|---|---|---|
| **M0 – Spike** | Sidecar bundling, ek task local workspace me chalana, basic chat UI | 2 weeks |
| **M1 – MVP (P0)** | Wizard, LLM config, chat, terminal, editor+diff, local workspace, confirmation mode, installer | 6–8 weeks |
| **M2 – Sandbox** | Docker/WSL2 mode, port preview, checkpoints | 4 weeks |
| **M3 – Integrations (P1)** | Git/GitHub PR flow, MCP, skills, secrets, browser panel | 6 weeks |
| **M4 – Scale (P1)** | Multi-agent, tray/notifications, cost budgets, auto-update | 4 weeks |
| **M5 – Polish/GA** | Perf, a11y, signing, docs, beta feedback | 4 weeks |
| **M6 – Later (P2)** | Remote runtimes, scheduler, CLI wrapper, i18n, Store | TBD |

---

## 15. Acceptance Criteria (MVP)

1. Fresh Windows 11 machine par installer se app install hota hai, Docker ke bina.
2. Wizard me API key dalke "Test connection" pass hota hai.
3. User folder select karke likhta hai: *"Ek Flask app banao jisme /health endpoint ho aur tests ho"* → agent files banata hai, tests chalata hai, results UI me dikhte hain.
4. Risky command (`rmdir /s`) par approval dialog aata hai; deny karne par command execute nahi hoti.
5. Agent ko Stop dabane par 2 sec ke andar rukta hai.
6. App close/reopen par conversation history resume ho jati hai.
7. Local model (Ollama) ke saath same flow offline chalta hai.
8. Diff view me user per-file accept/reject kar sakta hai.
9. API keys DB ya logs me plain text me nahi milti.
10. App crash ke baad sidecar orphan process nahi chhodta.

---

## 16. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Upstream V1 SDK API change hota rehta hai | Break | Version pin, adapter layer, upgrade CI job |
| Local mode me destructive commands | Data loss | Confirmation policy, path guard, auto-checkpoint |
| Docker/WSL2 setup user ke liye mushkil | Drop-off | Local mode default, guided setup |
| Image/runtime version mismatch (sandbox) | Start failure | App hi matching tags manage kare |
| Bundle size bada (Python + deps) | Download friction | Lazy-download optional components |
| Code-signing cost/delay | SmartScreen warning | Early certificate procurement |
| Prompt injection via web content | Security | SR-9, untrusted-content tagging, approvals |
| LLM cost overrun | User bill shock | Budget caps, live cost meter |
| Licensing (third-party deps) | Legal | License audit; OpenHands core MIT, dependencies check |

---

## 17. Open Questions

1. Tauri vs Electron final decision (node-pty/Monaco/WebView2 integration prototype ke baad).
2. Python sidecar ko PyInstaller se freeze karein ya embedded CPython + wheels?
3. Telemetry/crash reporting: kaunsa provider (self-hosted Sentry?)
4. Distribution: sirf direct download ya Microsoft Store bhi?
5. Upstream (OpenHands) ke saath contribute karein ya alag fork/app maintain karein?
6. Branding: "OpenHands" naam/logo use karne ke liye upstream trademark guidelines check karne hain.

---

## 18. Appendix

### 18.1 Suggested Repo Structure
```
openhands-desktop/
├─ apps/
│  ├─ shell/            # Tauri/Electron main process
│  └─ ui/               # React frontend
├─ sidecar/             # Python: wrapper over openhands-agent-server
│  ├─ pyproject.toml
│  └─ app/
├─ packages/
│  ├─ shared-types/     # TS types for events/API
│  └─ ui-kit/
├─ installer/           # NSIS/MSI scripts, signing
├─ docs/
├─ scripts/
└─ .github/workflows/
```

### 18.2 Glossary
- **Agent Server:** OpenHands ka HTTP/WebSocket service jo agent loop chalata hai.
- **Workspace:** Jahan agent files/commands execute karta hai (local/docker/remote).
- **Sandbox:** Isolated container environment.
- **MCP:** Model Context Protocol, tools ke liye standard.
- **Condenser:** Lambi history ko summarise karne wala component.
- **Confirmation mode:** Risky actions ke liye user approval.

### 18.3 References
- OpenHands Software Agent SDK paper: arXiv 2511.03690
- Docs: https://docs.openhands.dev
- SDK repo: https://github.com/OpenHands/software-agent-sdk
- CLI repo: https://github.com/OpenHands/OpenHands-CLI
