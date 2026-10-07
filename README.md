# harness

A personal agent manager: dispatch, watch, review and merge coding-agent work across your repos from a native Mac app or an iPhone web app.

harness is the app around the agent, not the agent itself. Agents run on the official Claude Code engine through the Claude Agent SDK, using your own Claude subscription login and your existing Claude Code setup (CLAUDE.md, skills, plugins, MCP servers, hooks). Agents never commit or push; harness does that after you approve in the UI.

Status: early development.

## Layout

| Path | What |
|---|---|
| `daemon/` | Python daemon (FastAPI, websockets, Claude Agent SDK, SQLite). Runs on the Mac as a background service. |
| `web/` | iPhone PWA (React, TypeScript, Vite), served by the daemon. |
| `apple/` | Native Mac app: a Swift package with the `HarnessKit` logic library and the `HarnessApp` SwiftUI executable (D024). |
| `design/` | `tokens.toml`, the design tokens shared by both clients (`make tokens` regenerates the CSS and Swift outputs). |

## Prerequisites

- macOS with [uv](https://docs.astral.sh/uv/) and Python 3.12
- Node.js with npm
- Claude Code, logged in with your subscription
- Xcode 27 or later (Mac app), Tailscale (iPhone access), the `gh` CLI logged in (pull requests)

## Development

```bash
make install   # install daemon and web dependencies
make check     # every quality gate: format, lint, types, tests with 100% coverage, build, audit
make fmt       # auto-format and auto-fix lint
make test      # tests only
make check-apple  # Swift lint, build, tests with 100% HarnessKit coverage
make app       # build apple/build/Harness.app (ad-hoc signed)
make run-app   # build and open the Mac app
make install-app  # build and copy Harness.app into /Applications
make tokens    # regenerate design token outputs
```

## Mac app

Approvals, questions and reviews are answered in the Needs you card or inline in the chat; reviews open a side-by-side diff and an approve sheet (commit message, push, pull request). Keyboard: Cmd-N new chat, Cmd-W close the focused pane, Cmd-1 to Cmd-9 project tabs, Cmd-Shift-[ and ] previous and next project, Cmd-K search and commands, Cmd-, settings, Cmd-Return send, Esc closes sheets. macOS notifications follow Settings > Notifications and are skipped for a chat that is on screen; the Dock badge counts pending approvals.

The window is see-through: it sits on the system's behind-window blur, so your real desktop shows through the glass (with Reduce Transparency on, macOS makes it opaque). See D038.

For visual review, a debug build renders the window offscreen without showing it: `cd apple && swift build && "$(swift build --show-bin-path)/HarnessApp" --render-snapshots <folder>` (sample data) or `--render-live <folder>` (the local daemon, read-only).

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

## iPhone access

The iPhone reaches the daemon through Tailscale, never the public internet. Once, on the Mac:

```bash
tailscale serve --bg 8765
```

Tailscale must have Serve and HTTPS certificates enabled for the tailnet (it prints a link the first time). The daemon is then available at `https://<mac-name>.<tailnet>.ts.net/` on devices signed in to the same tailnet; every API call still needs a paired device token. `tailscale serve --https=443 off` turns it off.

To install the phone app: run `uv run harness pair` in `daemon/` (or Settings > Devices > Pair a device in the Mac app), open the tailnet address in Safari on the iPhone, enter the code, then Share > Add to Home Screen. The daemon serves the built PWA from `web/dist` (override with `HARNESS_WEB_DIST`); run `cd web && npm run build` after changing it. Browser websocket connections must come from the same origin or from `server.allowed_origins` in `settings.toml`.

## Notifications

The phone is notified when an agent needs approval, asks a question, has work ready for review, fails or finishes a turn. Tapping a notification opens the inbox (approvals, questions, reviews) or the chat (failures, finished turns).

- **Web push** (free, built in): open the Home Screen app, then Account > Notifications > Enable notifications. iOS offers push only to the installed app, and asks for permission when you tap the button. Send test checks the whole path. The VAPID key pair is created on first use; its private key lives only in the Keychain (service `harness`, account `webpush-vapid-private`). Revoking a device deletes its subscriptions.
- **Rules** apply to every device and live in `settings.toml`; the Account tab edits them (`GET/PUT /api/notifications/settings`). Editing there rewrites `settings.toml` without its comments.

```toml
[notifications]
vapid_subject = "mailto:you@example.org"   # contact the push services see; Apple rejects localhost

[notifications.kinds]           # true by default, except the two pull request kinds
finished = false
ci_failed = true                # pull request checks failed (inbox always shows it)
ready_to_merge = true           # checks passed and GitHub can merge (inbox always shows it)

[notifications.quiet_hours]     # optional, the Mac's local time; may wrap past midnight
start = "22:00"
end = "07:00"

[notifications.ntfy]            # optional, off by default
enabled = true
server = "https://ntfy.sh"
topic = "harness-<long random string>"
click_base_url = "https://<mac-name>.<tailnet>.ts.net"   # makes a tapped ntfy message open the item
```

- **ntfy** is an optional second channel through the ntfy app. On a public server such as ntfy.sh, anyone who knows a topic can read its messages, so use a long random topic or a self-hosted server.

## Pull requests

After harness opens a pull request it follows it through your `gh` login: every minute, every five minutes once nothing changed for an hour, and no longer once it is merged or closed. The chat header shows a chip with the number and a dot for the checks (amber running, green passed, red failed). When checks fail, the inbox shows the failing check names with **Send to agent**, which sends "CI failed: <names>. Please fix." into the chat. When the checks pass (or there are none) and GitHub can merge it, a merge approval appears with **Merge (squash)** and **Open on GitHub**; merging also closes the chat and removes its worktree and branch. Agents can still never merge. Each pull request keeps a short summary from the agent's final summary and the diff stats, without a model call. See D034.

## Search

The search field at the top of the Projects tab finds chats across every project by title and by what was said: your messages, Claude's replies, tool calls (name and main argument) and the start of tool output, plus the titles of Claude Code chats. Words must all match; `"quoted phrases"` match in order and `word*` matches a prefix. Results are grouped by chat, best match first; tapping one opens the chat scrolled to that message, highlighted for a moment. The index lives in the daemon's SQLite database (FTS5) and is filled from stored events; on the first start after the upgrade it indexes the existing history in the background. See D035.

## Models, account and agent defaults

The model and thinking selectors list exactly what Claude Code offers: the daemon reads the model list and the signed-in account from Claude Code's startup handshake (a short-lived process with your user settings, no tools and no transcript; no model call, no tokens) on start and every 6 hours, and every agent run refreshes them. They are cached in the database; until Claude Code has answered once, the selectors offer the aliases Default, Opus, Sonnet and Haiku. Thinking shows only the levels the chosen model takes (Extra high and Max included) and is not available for Haiku. Account > Profile shows the name (when Claude Code reports one) and plan; the email stays hidden until you tap Show. See D038.

New chats use the agent defaults (Settings > Agent defaults on the Mac, Account > Agent defaults in the iPhone app, or `PUT /api/agents/defaults`) for anything the composer leaves unset. New chats work in place unless the defaults say Worktree; a repo's `[worktree] default = true` or `false` overrides that for the repo, and a repo file without it follows the default. A thinking level the chosen model does not take is refused (422) when chosen, and dropped when it only comes from the defaults.

```toml
[agents]
model = "opus"               # a value from the model list; leave out for Claude Code's default
effort = "high"              # low, medium, high, xhigh or max; leave out for the model's default
permission_mode = "default"  # default, acceptEdits, plan or bypassPermissions
default_mode = "in_place"    # or "worktree"
```

## Stuck chats

harness flags a running chat as stuck when it waits on a permission prompt, question or plan for too long, runs without any new output, repeats the same tool call with the same input, or runs one turn very long. A stuck chat shows a **Stuck** badge in the chat list and a card in the inbox with the reason, **Interrupt**, and **Send a nudge**, which stops the turn and sends "You seem stuck: <reason>. Step back and try a different approach." The flag clears as soon as the condition ends. Pushing it to the phone is off by default (Account > Notifications). See D036.

```toml
[stuck]
waiting_minutes = 15  # on a prompt; 0 turns a check off
silent_minutes = 10   # no new output
repeated_calls = 4    # the same call more than this many times in a row
turn_minutes = 60     # one turn
```

## Usage numbers

Claude reports the 5 hour and weekly limits only with a turn, so harness refreshes them with a tiny probe (Haiku, no tools, settings, MCP servers or thinking; about 400 input tokens) every `usage.refresh_minutes` (default 3) while the Mac app or the iPhone app is on screen, skipping when a harness turn reported them within the interval. Clients report that they are visible with `POST /api/clients/visibility` on show, on hide and every minute while shown. Probe tokens are listed apart (`probes` in the month) and never counted as your sessions. Each window shows "as of HH:MM", dimmed after 10 minutes, and Refresh asks at once. See D031.

```toml
[usage]
refresh_minutes = 3   # 0 turns the automatic refresh off; Refresh still works
```

## Claude Code chats

harness lists the Claude Code chats of each registered repo (from the terminal, the desktop app or an editor), read from `~/.claude/projects` (or `$CLAUDE_CONFIG_DIR`), never written. Chats a program started through an Agent SDK (entrypoint `sdk-py` and the like, such as automated security reviews) are hidden unless "Show automated chats" is switched on (per device). A chat opens read-only; "Continue in harness" turns it into a harness session in the chat's own folder, and the next message resumes it. Sending is refused while the chat is open in Claude Code. New harness worktrees live in `<repo>/.claude/worktrees/harness-<id>` (excluded in the repo's `.git/info/exclude`), so `claude --resume` in the project finds harness chats too. The Claude desktop app only lists chats it started itself. See D028.

## Claude Code chats in the Mac app

Chats you started in Claude Code (Terminal or the Claude desktop app) for a registered project appear in the sidebar's Idle group with a "Claude Code" label. Opening one shows its history read-only; **Continue in harness** takes it over. Automated SDK runs are hidden unless **Settings > Claude Code chats > Show automated chats** is on. Sending is refused while the chat is open in Claude Code.

Dictation uses Apple's on-device `SpeechAnalyzer` (macOS 26 and later), downloading the language model on first use, with project names and coding terms as hints; it falls back to the older speech recognizer when needed.

## Claude Code conveniences

In a chat, typing `/` at the start of the message suggests the session's slash commands and skills, and `@` suggests files of the working directory (inserted as `@path`); Claude Code expands both when the message arrives. A plan Claude finishes in plan mode appears as a plan card with **Approve plan** (the chat continues in Accept edits) and **Keep planning** (with an optional note). A quiet "context N%" next to the composer selectors shows how full the context window is, with **Compact** (sends `/compact`). A message sent while Claude works is queued, shown under the transcript with a cancel button, and sent when the turn ends. See D032.

The Mac app reports itself as visible (client `mac`) while its window is on screen, shows "as of" times dimmed when older than 10 minutes, a Refresh button, and the refresh interval under Settings > Usage. Thinking can be changed on open chats; it applies from the next message.

## Terminal and browser panes

The Mac workspace can hold terminals and browsers next to chats (still up to four panes). New terminal: project menu, palette or Cmd+Shift+T; "Terminal here" opens one in a chat's folder. New browser: project menu, palette or Cmd+Shift+B; the address field accepts a bare port (`3000`), `localhost:3000` or a URL, and "Local servers" lists dev servers listening on this Mac. Shell code blocks in chats offer Copy and **Run in terminal**, which runs the command in the chat folder's terminal.

## Pull requests in the Mac app

Chats with an open PR show `#number` with a checks dot in the pane header and on the Board; click it for the checks list, Refresh and Open on GitHub. Needs you shows a merge card once checks pass (squash by default) and a "Checks failed" card with "Send to agent".

In the Mac app, Cmd+K also searches messages across all chats (a "Messages" section) and jumps to the hit with a short highlight. Stuck chats get an amber Stuck badge and a Needs you card with Send a nudge and Interrupt; thresholds live in Settings > Stuck chats.

## API overview

All routes need a device token (`Authorization: Bearer <token>` or the `harness_token` cookie), except `GET /api/health` and `POST /api/pairing/redeem`.

| Area | Routes |
|---|---|
| Devices | `POST /api/pairing/codes`, `POST /api/pairing/redeem`, `GET /api/devices`, `DELETE /api/devices/{id}` |
| Repos | `GET/POST /api/repos`, `GET/DELETE /api/repos/{name}` (`?purge_sessions=true` also deletes its sessions; the folder is never touched), `GET /api/repos/{name}/link-suggestions`, `PUT /api/repos/{name}/worktree` (`default` true or false overrides the agent default mode for the repo; null follows it), `GET /api/repos/{name}/commands` (slash commands of the repo's latest agent run, for new chats) |
| Sessions | `GET/POST /api/sessions`, `GET/PATCH/DELETE /api/sessions/{id}` (the detail adds `tasks`, `agents` and `background`, the running and completed subagents and background commands, and `queued`, the follow-ups waiting for the turn; every session has `context`, how full the context window is, and `stuck`, `{reason, since, details}` or null), `GET /api/sessions/{id}/events?after=&before=&limit=` (oldest first; with `limit`, the events nearest `before` when given, else nearest `after`, for paging around a search hit), `POST /api/sessions/{id}/messages` (202; while a turn runs the message is queued and `queued_message` is set, and with `interrupt: true` the turn is stopped and the message runs next, ahead of the queue; 409 with `code: "open_in_claude_code"` while Claude Code has the chat open), `DELETE /api/sessions/{id}/queue/{queued_id}`, `POST /api/sessions/{id}/interrupt`, `GET /api/sessions/{id}/commands` (slash commands and agents), `GET /api/sessions/{id}/files?q=` (up to 50 files for @ mentions) |
| Claude Code chats | `GET /api/claude-chats?repo=&include_automated=` (chats of registered repos that harness does not own; automated ones only with `include_automated=true`, each with `entrypoint` and `automated`), `GET /api/claude-chats/{id}`, `GET /api/claude-chats/{id}/events` (read-only history as session events), `POST /api/claude-chats/{id}/adopt` (continue in harness: 201 with the new session, 200 with the existing one) |
| Review | `GET /api/sessions/{id}/diff`, `POST /api/sessions/{id}/approve`, `POST /api/sessions/{id}/reject`, `POST /api/sessions/{id}/feedback` |
| Approvals | `GET /api/approvals`, `GET /api/approvals/{id}`, `POST /api/approvals/{id}/resolve` (kinds `permission`, `question`, `plan` with `decision` `approve` or `keep_planning`, `review`, and `merge`, which only takes `{"dismiss": true}`) |
| Pull requests | `GET /api/prs?repo=&state=open\|merged\|closed\|all` (default open; pull requests harness opened, each `{session_id, repo, session_title, session_state, url, summary, pr}`), `POST /api/sessions/{id}/merge` (`{method: squash\|merge\|rebase, delete_branch}`, defaults squash and true; closes the session and removes its worktree; 502 with `step` and `stderr` when gh fails, 409 without an open pull request or while the agent works), `POST /api/sessions/{id}/pr/refresh` (read it from GitHub now; 502 when gh fails). Every session has `pr` (last known status or null) and `pr_summary` |
| Search | `GET /api/search?q=&repo=&limit=` (`q` 1 to 200 characters, `limit` 1 to 100, default 20): `{hits: [{session_id, repo, title, event_id, ts, kind, snippet}], indexing}`, best match first; `kind` is `title`, `user`, `assistant`, `tool`, `tool_result` or `claude_chat` (then `session_id` is the Claude Code chat id); `event_id` is null for titles; matches in `snippet` are wrapped in `[[` and `]]` |
| Stuck | `GET/PUT /api/stuck/settings` (`{waiting_minutes, silent_minutes, repeated_calls, turn_minutes}`); events `session.stuck` `{reason: waiting\|silent\|repeating\|long_turn, since, details}` and `session.unstuck` `{reason}`; `notify` kind `stuck` |
| Models and defaults | `GET /api/models` (`{models: [{value, display_name, description, effort_levels, supports_effort}], updated_at}` in Claude Code's order; `updated_at` null for the built-in aliases), `GET /api/account` (`{display_name, email, plan, organization}`, each nullable), `GET/PUT /api/agents/defaults` (`{model, effort, permission_mode, mode: in_place\|worktree}`; 422 when the model does not take the effort) |
| Attachments | `POST /api/attachments` |
| Organize | `PATCH /api/sessions/{id}` (title, pinned, archived, model, permission mode, effort; a new effort applies from the next message), `DELETE /api/sessions/{id}?purge=true`, `GET /api/sessions?repo=&archived=` |
| Notifications | `GET /api/push/vapid-key`, `POST/DELETE /api/push/subscribe` (the caller's own subscriptions), `POST /api/push/test`, `GET/PUT /api/notifications/settings` |
| Connectors and usage | `GET /api/connectors`, `GET /api/usage/month?year=&month=` (probe tokens apart in `probes`), `GET /api/usage/limits`, `POST /api/usage/refresh` (429 with `Retry-After` within 20 s of the last probe, 502 when Claude reports nothing), `GET/PUT /api/usage/settings`, `POST /api/clients/visibility` |
| Local apps | `POST /api/sessions/{id}/open-in-claude-code`, `POST /api/repos/{name}/open` (`vscode`, `finder`, `terminal`) |
| Events | `WS /api/events?after=<id>` (replay, then live; text deltas and `claude_chats.updated` arrive with `id: null`) |

Coverage is enforced at 100%: daemon line and branch coverage, and web lines, branches, functions and statements.
