# Roadmap

What is built, and what is deliberately left for later. Nothing here is required for the app to
install, onboard and run an agent against a local project.

## Shipped

- Electron shell with managed sidecar, session-token auth, crash notification and clean shutdown.
- Onboarding wizard, provider management with live connection tests, encrypted key vault.
- Agent loop with streaming events, pause/resume/stop, approvals, cost and token accounting.
- Tools: shell, read/write/replace file, tree listing, web fetch, plan, finish.
- Workspace file explorer with git markers, editor, diff review with accept/reject.
- Interactive PTY terminal (ConPTY on Windows, `pty` on POSIX) streamed over WebSocket.
- Conversation history, search, pin, export, persisted events.
- Windows NSIS installer pipeline with an embedded CPython runtime.

## Next

1. **Auto-update** — `electron-updater` against GitHub Releases (signed builds first).
2. **Code signing** — an EV certificate to avoid SmartScreen warnings on first run.
3. **Syntax highlighting in the editor** — currently a plain monospace textarea.
4. **Inline image/preview pane** for screenshots the agent generates.
5. **Multi-tab terminal** with a shell picker (PowerShell / cmd / WSL / bash).
6. **ARM64 installer** — the bundling script already accepts `--arch arm64`.
7. **Conversation branching** — fork a conversation from an earlier event.
8. **Sandbox default** — offer the Docker workspace in onboarding when Docker is detected.

## Known limitations

- The terminal writes UTF-8 over the socket; full-screen TUIs work, but very high-throughput
  output may drop frames because chunks are coalesced before sending.
- The diff view handles text files only.
- `pywinpty` is required for the terminal on Windows; it ships with the installer, but a
  source checkout on Windows must install it (`pip install -e sidecar` pulls it in via the
  platform marker).
