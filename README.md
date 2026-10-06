# harness

A personal agent manager: dispatch, watch, review and merge coding-agent work across your repos from a native Mac app or an iPhone web app.

harness is the app around the agent, not the agent itself. Agents run on the official Claude Code engine through the Claude Agent SDK, using your own Claude subscription login and your existing Claude Code setup (CLAUDE.md, skills, plugins, MCP servers, hooks). Agents never commit or push; harness does that after you approve in the UI.

Status: early development.

## Layout

| Path | What |
|---|---|
| `daemon/` | Python daemon (FastAPI, websockets, Claude Agent SDK, SQLite). Runs on the Mac as a background service. |
| `web/` | iPhone PWA (React, TypeScript, Vite), served by the daemon. |
| `apple/` | Native Mac app (SwiftUI) and its `HarnessKit` logic package. Not created yet. |
| `design/` | Design tokens shared by both clients. Not created yet. |

## Prerequisites

- macOS with [uv](https://docs.astral.sh/uv/) and Python 3.12
- Node.js with npm
- Claude Code, logged in with your subscription
- Later phases: Xcode (Mac app), Tailscale (iPhone access), the `gh` CLI logged in (pull requests)

## Development

```bash
make install   # install daemon and web dependencies
make check     # every quality gate: format, lint, types, tests with 100% coverage, build, audit
make fmt       # auto-format and auto-fix lint
make test      # tests only
```

## Running the daemon

```bash
cd daemon
uv run harness serve              # run in the foreground on 127.0.0.1:8765
uv run harness service install    # install and start the launchd background service
uv run harness service status     # exit 0 when the service is loaded
uv run harness service uninstall  # stop and remove it
uv run harness pair               # print a one-time pairing code for a new device
```

- Config: `~/.config/harness/` (override with `HARNESS_CONFIG_DIR`). A default `settings.toml` is written on first run.
- Data and logs: `~/Library/Application Support/harness/` (override with `HARNESS_DATA_DIR`); the service logs to `logs/daemon.log` there.
- The Mac's own device token lives in the macOS Keychain (service `harness`).

## API overview

All routes need a device token (`Authorization: Bearer <token>` or the `harness_token` cookie), except `GET /api/health` and `POST /api/pairing/redeem`.

| Area | Routes |
|---|---|
| Devices | `POST /api/pairing/codes`, `POST /api/pairing/redeem`, `GET /api/devices`, `DELETE /api/devices/{id}` |
| Repos | `GET/POST /api/repos`, `GET /api/repos/{name}`, `GET /api/repos/{name}/link-suggestions`, `PUT /api/repos/{name}/worktree` |
| Sessions | `GET/POST /api/sessions`, `GET/PATCH/DELETE /api/sessions/{id}`, `GET /api/sessions/{id}/events`, `POST /api/sessions/{id}/messages`, `POST /api/sessions/{id}/interrupt` |
| Review | `GET /api/sessions/{id}/diff`, `POST /api/sessions/{id}/approve`, `POST /api/sessions/{id}/reject`, `POST /api/sessions/{id}/feedback` |
| Approvals | `GET /api/approvals`, `GET /api/approvals/{id}`, `POST /api/approvals/{id}/resolve` |
| Attachments | `POST /api/attachments` |
| Organize | `PATCH /api/sessions/{id}` (title, pinned, archived, model, permission mode), `DELETE /api/sessions/{id}?purge=true`, `GET /api/sessions?repo=&archived=` |
| Connectors and usage | `GET /api/connectors`, `GET /api/usage/month?year=&month=`, `GET /api/usage/limits` |
| Local apps | `POST /api/sessions/{id}/open-in-claude-code`, `POST /api/repos/{name}/open` (`vscode`, `finder`, `terminal`) |
| Events | `WS /api/events?after=<id>` (replay, then live; text deltas arrive with `id: null`) |

Coverage is enforced at 100%: daemon line and branch coverage, and web lines, branches, functions and statements.
