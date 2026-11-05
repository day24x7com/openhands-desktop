# AGENTS.md

Notes for agents working in this repository (OpenHands Desktop: Electron shell + React UI + Python sidecar).

## Commands

```bash
# tests (each workspace is independent)
/tmp/ci-venv/bin/python -m pytest sidecar/tests -q      # sidecar
cd apps/ui && npx vitest run                            # UI
cd apps/shell && npm test                               # Electron supervisor (spawns real Python, ~5s)

# lint / types / build
/tmp/ci-venv/bin/ruff check sidecar/app sidecar/tests
cd apps/ui && npx tsc -b && npm run build
```

`ruff` enforces import sorting (isort rules) — run it before committing.

## Conventions

- **snake_case on the wire.** Python models, `packages/shared-types` and the UI agree on
  `snake_case`; only the IPC config object passed through `preload.ts` is camelCase.
- **Docs must be derived from code, not written from memory.** Routes in `docs/API.md` are
  enumerated from `sidecar/app/main.py`; payload shapes were verified with live requests.
  Doing this surfaced several real bugs (see below).
- **Tests hit real things**: real git repos, real PTY shells, real sidecar processes. Avoid
  mocks except at the LLM boundary (`MockLLM`, whose `.calls` records what the model received —
  assert on that to prove data actually reaches the model).

## Gotchas learned the hard way

- `git add -- -A` treats `-A` as a pathspec. Use `["add", "-A"]` or `["add", "--", *paths]`.
- `Workspace._git()` swallows stderr and returns `""`; use `_git_checked()` when the user needs
  to see why a git command failed.
- PTY tests: the terminal **echoes typed text**, so `read_until("marker")` matches the echoed
  command before its output. Wait for the resolved value plus `\r\n`.
- Attachment `data` is base64. Text attachments must be decoded before inlining into the prompt;
  images must be sent as `image_url` parts (Anthropic needs `_to_anthropic_blocks`).
- Conversations end in status `done`, not `idle` — `wait_for_status` must accept both.
- UI tests need `@testing-library/jest-dom/vitest` in `src/test-setup.ts` for
  `toBeInTheDocument`.
- Vite build: xterm is in its own chunk via `manualChunks` so the initial bundle stays ~50 kB.

## Layout reminders

- `sidecar/app/main.py` is large (all routes). `AppState` (`app.state.ohd`) holds DB, runtimes,
  terminal registry and settings; it also records `started_at` for `/health`.
- Auth is a bearer token minted by the Electron shell; `/health` is the only unauthenticated
  route. WebSockets take the token as a query parameter.
