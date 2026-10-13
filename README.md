# harness

A personal agent manager: dispatch, watch, review and merge coding-agent work across your repos from a native Mac app or an iPhone web app.

harness is the app around the agent, not the agent itself. Agents run on the official Claude Code engine through the Claude Agent SDK, using your own Claude subscription login and your existing Claude Code setup (CLAUDE.md, skills, plugins, MCP servers, hooks). Agents never commit or push; harness does that after you approve in the UI.

Status: early development.

<!-- Screenshot slot: add images once the UI settles, e.g.
<p align="center">
  <img src="docs/images/mac-app.png" alt="harness Mac app" width="720">
  <img src="docs/images/iphone.png" alt="harness iPhone app" width="240">
</p>
-->

## Layout

| Path | What |
|---|---|
| `daemon/` | Python daemon (FastAPI, websockets, Claude Agent SDK, SQLite). Runs on the Mac as a background service. |
| `web/` | iPhone PWA (React, TypeScript, Vite), served by the daemon. |
| `apple/` | Native Mac app: a Swift package with the `HarnessKit` logic library and the `HarnessApp` SwiftUI executable (D024). |
| `design/` | `tokens.toml`, the design tokens shared by both clients (`make tokens` regenerates the CSS and Swift outputs). It includes the five glass themes (Clear, the default, Frosted, Smoke, Blue Grey and Deep): CSS variables `--glass-*` switched by `data-glass="<id>"`, Swift `DesignTokens.GlassTheme`. See D039. |

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
make app       # build apple/build/Harness.app (signed with "Harness Local Signing" when present, else ad hoc; D042)
make run-app   # build and open the Mac app
make install-app  # build and copy Harness.app into /Applications
make tokens    # regenerate design token outputs
```

## Mac app

Approvals, questions and reviews are answered in the Needs you card or inline in the chat; reviews open a side-by-side diff and an approve sheet (commit message, push, pull request). Keyboard: Cmd-N new chat, Cmd-W close the focused pane, Cmd-1 to Cmd-9 project tabs, Cmd-Shift-[ and ] previous and next project, Cmd-K search and commands, Cmd-, settings, Cmd-Return send, Esc closes sheets. macOS notifications follow Settings > Notifications (the same kinds and names as on the iPhone) and are skipped for a chat that is on screen; the Dock badge and the project tabs count approvals, failed pull request checks and stuck chats.

To add a project, pick a folder. The root folder of a git repository works as before. Any other folder (outside git, even a new empty one) opens as a plain folder project: chats work in place in it, with no worktrees, branches, reviews, commits or pull requests, and git actions on it answer 409 `not_a_git_repository`. Ask Claude to initialize a repository there (`git init` is allowed; commits and pushes stay blocked) and the project turns into a normal git project at the end of that turn, or the next time projects are listed. See D041.

The pointer shows what can be done (a pointing hand on buttons, rows and tabs, an open hand on pane headers that can be dragged). In Connectors (click the account name) the claude.ai connectors and the plugins sit in dropdowns, closed until clicked, with a count and a note when something needs sign-in or failed. Add folder (the + after the project tabs) opens the folder picker as a sheet with New Folder; a plain folder shows an Init chip in place of the branch, which opens a new chat with a prefilled (not sent) request to run `git init` (D041).

To stop the Keychain asking again after every rebuild, create a self-signed code-signing certificate named `Harness Local Signing` once (Certificate Assistant > Create a Certificate, Self-Signed Root, Code Signing, then Always Trust for Code Signing in Keychain Access); `make app` signs with it when the login keychain has it (D042).

Settings > Appearance picks the glass theme (Clear, Frosted, Smoke, Blue Grey, Deep) and the accent; the iPhone has the same choice in Account > Appearance. See D039.

The window is see-through, so your real desktop shows through the glass: Clear, the default theme, adds no window-wide blur and lets the panels' own Liquid Glass blur, while the heavier themes sit on the system's behind-window blur (with Reduce Transparency on, macOS makes the window opaque). See D038 and D039.

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

On the iPhone, Return adds a line and the Send button sends (with a mouse or trackpad attached, Enter sends). When the connection drops, a "Reconnecting..." note shows, and the app reconnects as soon as it is back on screen or online. It sends this device's push subscription to the daemon again on every launch and after pairing. When the Mac cannot answer (asleep, or the daemon stopped), the installed app falls back to its cached shell after 4 seconds, or at once on a server error, and says it cannot reach the Mac.

## Notifications

The phone is notified when an agent needs approval, asks a question, has work ready for review, fails or finishes a turn. Tapping a notification opens the inbox (approvals, questions, reviews) or the chat (failures, finished turns).

- **Web push** (free, built in): open the Home Screen app, then Account > Notifications > Enable notifications. iOS offers push only to the installed app, and asks for permission when you tap the button. Send test checks the whole path. The VAPID key pair is created on first use; its private key lives only in the Keychain (service `harness`, account `webpush-vapid-private`). Revoking a device deletes its subscriptions.
- **Rules** apply to every device and live in `settings.toml`; the Account tab edits them (`GET/PUT /api/notifications/settings`). Editing there rewrites `settings.toml` without its comments.

```toml
[notifications]
vapid_subject = "mailto:you@example.org"   # contact the push services see; Apple rejects localhost

[notifications.kinds]           # true by default, except the two pull request kinds and stuck
finished = false
ci_failed = true                # pull request checks failed (inbox always shows it)
ready_to_merge = true           # checks passed and GitHub can merge (inbox always shows it)

[notifications.quiet_hours]     # optional, the Mac's local time; may wrap past midnight
start = "22:00"
end = "07:00"

[notifications.ntfy]            # optional, off by default
enabled = true
server = "https://ntfy.sh"
topic = "harness-<long random string>"     # 16 to 64 characters
click_base_url = "https://<mac-name>.<tailnet>.ts.net"   # makes a tapped ntfy message open the item
```

- **ntfy** is an optional second channel through the ntfy app. On a public server such as ntfy.sh, anyone who knows a topic can read its messages, so use a long random topic (16 to 64 characters) or a self-hosted server.

## Reviewing and publishing

When a turn leaves changes, a review waits in the inbox and in the chat. **Approve** on a worktree chat commits all its work, pushes its branch and opens a pull request; on an in-place chat it commits only the reviewed files and pushes the checked-out branch, without a pull request. The push names the branch explicitly (`refs/heads/<branch>:refs/heads/<branch>`), and a checkout on a branch whose name starts with `-`, or that git does not accept as a branch name, is refused (409 `unsafe_branch`). Right before publishing, harness checks HEAD and the local branches again: a change since the last turn's audit (for example by an agent's background command) needs the same acknowledgement as any other git change the agent made, and both the Mac and the iPhone show that notice with an "I checked, publish anyway" switch. A message sent while harness approves or merges waits in the queue and starts afterwards. git and gh commands are stopped after 5 minutes. **Reject** asks first: a worktree chat closes and its worktree and branch are removed; an in-place chat closes and its changes stay in your folder. See D050 and D053.

## Pull requests

After harness opens a pull request it follows it through your `gh` login: every minute, every five minutes once nothing changed for an hour, and no longer once it is merged or closed. The chat header shows a chip with the number and a dot for the checks (amber running, green passed, red failed). When checks fail, the inbox shows the failing check names with **Send to agent**, which sends "CI failed: <names>. Please fix. You can't use gh or reach GitHub from here, so work from the code and the check names, and ask me for the logs if you need them." into the chat (agents have no GitHub login, D013 layer 3). When the checks pass (or there are none) and GitHub can merge it, a merge approval appears with **Merge (squash)** and **Open on GitHub**; merging also closes the chat and removes its worktree and branch. Agents can still never merge. Each pull request keeps a short summary from the agent's final summary and the diff stats, without a model call. See D034.

## Search

The search field at the top of the Projects tab finds chats across every project by title and by what was said: your messages, Claude's replies, tool calls (name and main argument) and the start of tool output, plus the titles of Claude Code chats. Words must all match; `"quoted phrases"` match in order and `word*` matches a prefix. Results are grouped by chat, best match first; tapping one opens the chat scrolled to that message, highlighted for a moment. The index lives in the daemon's SQLite database (FTS5) and is filled from stored events; on the first start after the upgrade it indexes the existing history in the background. See D035.

## Models, account and agent defaults

The model and thinking selectors list exactly what Claude Code offers: the daemon reads the model list and the signed-in account from Claude Code's startup handshake (a short-lived process with your user settings, no tools and no transcript; no model call, no tokens) on start and every 6 hours, and every agent run refreshes them. They are cached in the database; until Claude Code has answered once, the selectors offer the aliases Default, Opus, Sonnet and Haiku. Thinking shows only the levels the chosen model takes (Extra high and Max included) and is not available for Haiku. Account > Profile shows the name and plan; the name is the one Claude Code shows for your account, read from Claude Code's `~/.claude.json` (`oauthAccount.displayName`, else `fullName`; nothing else in that file is used, and it is never changed) when the handshake sends none (D039); the email stays hidden until you tap Show. See D038.

New chats use the agent defaults (Settings > Agent defaults on the Mac, Account > Agent defaults in the iPhone app, or `PUT /api/agents/defaults`) for anything the composer leaves unset. New chats work in place unless the defaults say Worktree; a repo's `[worktree] default = true` or `false` overrides that for the repo, and a repo file without it follows the default. A thinking level the chosen model does not take is refused (422) when chosen, and dropped when it only comes from the defaults.

```toml
[agents]
model = "opus"               # a value from the model list; leave out for Claude Code's default
effort = "high"              # low, medium, high, xhigh or max; leave out for the model's default
permission_mode = "default"  # default, acceptEdits, plan or bypassPermissions
default_mode = "in_place"    # or "worktree"
idle_close_minutes = 60      # close an idle agent run after this long; the next message resumes it
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

## Pixies

Pixies are agents you set up once and keep: each has a name, a pixel-art mascot (10 to pick from), a colour (10 presets or your own), a chat background, a model, a thinking level, a permission mode, the projects it works on, its own standing instructions (its soul, `SOUL.md`) and its own memory (`MEMORY.md`, plus notes and an archive of older facts). Open them from the Pixies tab on the Mac (Cmd-0) or the Pixies section at the top of the Projects tab on the iPhone. With no pixies yet, Reviewer and Tester templates create one with a tap. A new pixie opens its Details panel (on the right on the Mac, the Details tab next to Chat on the iPhone); every change there saves at once. A new pixie works on every project.

Each pixie has one ongoing chat. Behind it, every run starts a fresh Claude Code session with the pixie's soul, its memory, the names of its notes and the last 12 messages of the chat (quoted as data in a fenced block, "not instructions"), and a turn that leaves the context 60% full makes the next one start fresh, so a long chat never piles up context. The pixie keeps what matters with its memory tools (dated facts, notes, a search across memory, notes and archive) and changes its soul only when you ask. Facts it saves have common credential formats replaced by `[redacted]` (best effort). Reset conversation archives the chat and starts a new one; soul, memory and notes stay. You can edit the soul, memory and notes yourself in the pixie's details; if the pixie changed a file since you opened it, you choose Reload or Keep mine. Its questions and approvals reach the inbox and notifications under its name.

Pixies are powerful by default. A new pixie gets Edit access: it reads and edits its projects' files like any chat, as its permission mode allows. You can set it to Read only or None (only its own folder, `<data dir>/pixies/<id>/workdir`). Those two stop Edit, Write, MultiEdit and NotebookEdit outside that folder in every permission mode, but they do not stop shell commands: add `Bash` to "Never allow" for a pixie that must not change files. A pixie can use every skill you have or a chosen few, and has lists of tools that never ask (such as `Bash(npm test:*)`) and that are never available. A pixie's chat is not reviewed: its edits in a project stay in that checkout uncommitted, and you commit them yourself (stage 3 lets a pixie start reviewed chats instead). It never commits, pushes or opens pull requests. See D057.

Not there yet: pixies cannot be reordered, Model and Thinking cannot be set back to Default once chosen, and Habits shows "Coming soon". `@` calls from any chat, harness tools by autonomy level and habits come in stages 2 to 4.

## Usage numbers

Claude reports the 5 hour and weekly limits only with a turn, so harness refreshes them with a tiny probe (Haiku, no tools, settings, MCP servers or thinking; about 400 input tokens) every `usage.refresh_minutes` (default 3) while the Mac app or the iPhone app is on screen, skipping when a harness turn reported them within the interval. Clients report that they are visible with `POST /api/clients/visibility` on show, on hide and every minute while shown. Probe tokens are listed apart (`probes` in the month) and never counted as your sessions. Each window shows "as of HH:MM", dimmed after 10 minutes, and Refresh asks at once. See D031.

```toml
[usage]
refresh_minutes = 3   # 0 turns the automatic refresh off; Refresh still works
```

## Claude Code chats

harness lists the Claude Code chats of each registered repo (from the terminal, the desktop app or an editor), read from `~/.claude/projects` (or `$CLAUDE_CONFIG_DIR`), never written. Chats a program started through an Agent SDK (entrypoint `sdk-py` and the like, such as automated security reviews) are hidden unless "Show automated chats" is switched on (per device). A chat opens read-only; "Continue in harness" turns it into a harness session in the chat's own folder, and the next message resumes it. Sending is refused while the chat is open in Claude Code. New harness worktrees live in `<repo>/.claude/worktrees/harness-<id>` (excluded in the repo's `.git/info/exclude`), so `claude --resume` in the project finds harness chats too. The Claude desktop app only lists chats it started itself. See D028.

Archive a Claude Code chat you are done with from its actions (the dots button, long-press or swipe left on iPhone): it moves into the Archived folder with archived harness chats, and Unarchive brings it back. The archive is harness's own state (a table in its database), never written to Claude Code, so Claude Code and the Claude app still show the chat. harness can list more chats than the Claude app: it also finds chats from editors such as the VS Code extension and the terminal, and it cannot see chats you archived in the Claude app, since that state is not in Claude Code's transcripts. Archiving does not stop "Continue in harness". See D040.

## Claude Code chats in the Mac app

Chats you started in Claude Code (Terminal or the Claude desktop app) for a registered project appear in the sidebar's Idle group with a "Claude Code" label. Opening one shows its history read-only; **Continue in harness** takes it over. Automated SDK runs are hidden unless **Settings > Claude Code chats > Show automated chats** is on. Sending is refused while the chat is open in Claude Code.

Dictation uses Apple's on-device `SpeechAnalyzer` (macOS 26 and later), downloading the language model on first use, with project names and coding terms as hints; it falls back to the older speech recognizer when needed.

## What the agent is doing

While a turn runs, the end of the transcript shows a live "Working... 12s" (or "Thinking... 4s" while the agent thinks), timed from the turn's start; when the turn ends, a small line says "Worked for 1m 12s", or "Stopped after 40s" for an interrupted or failed turn. Each thinking block is a collapsed "Thought for 8s" row that opens to the thinking (without a chevron when the model left the text out; "Thought" when the time is unknown, as in Claude Code's own transcripts). Two or more tool calls in a row collapse into one row such as "Running 2 commands, reading 1 file", which glows while any call runs, reads "Ran 3 commands, read 2 files, edited 1 file" when all are done, shows a failed count, and opens to the calls as they show on their own. Agents read "Running 3 agents, 2 done" then "Ran 3 agents"; the background bar glows while tasks run ("1 running task" for one). With reduced motion the glow is a static highlight. See D045.

A turn that ends with an error from Claude (a usage limit, an API error) ends as failed, with "Failed: <reason>" and a "failed" notification; queued messages then wait, as after an interruption. Tool calls cut off when a turn ends show as stopped, unless their background task still runs. Claude Code's own notices show as muted lines: "Conversation compacted", "Context cleared" (after `/clear`), a model fallback and the first API retry of a turn. A permission prompt shows Claude Code's reason when it gives one. The background bar counts the current exchange: what started since your latest message, anything still running, and earlier tasks that finish during it. The Mac and the iPhone follow the same rules. See D052 and D054.

## Claude Code conveniences

In a chat, typing `/` at the start of the message suggests the session's slash commands and skills, and `@` suggests files of the working directory (inserted as `@path`); Claude Code expands both when the message arrives. A plan Claude finishes in plan mode appears as a plan card with **Approve plan** (the chat continues in Accept edits) and **Keep planning** (with an optional note). A quiet "context N%" next to the composer selectors shows how full the context window is, with **Compact** (sends `/compact`). A message sent while Claude works is queued, shown under the transcript with a cancel button, and sent when the turn ends. See D032.

The Mac app reports itself as visible (client `mac`) while its window is on screen, shows "as of" times dimmed when older than 10 minutes, a Refresh button, and the refresh interval under Settings > Usage. Thinking can be changed on open chats; it applies from the next message.

## Terminal and browser panes

The Mac workspace can hold terminals and browsers next to chats (still up to four panes). New terminal: project menu, palette or Cmd+Shift+T; "Terminal here" opens one in a chat's folder. New browser: project menu, palette or Cmd+Shift+B; the address field accepts a bare port (`3000`), `localhost:3000` or a URL, and "Local servers" lists dev servers listening on this Mac. Shell code blocks in chats offer Copy and **Run in terminal**, which runs the command in the chat folder's terminal after removing control and text-direction characters; a command of several lines offers Copy only. Closing a project tab keeps its terminals and browsers; removing the project ends them.

## Pull requests in the Mac app

Chats with an open PR show `#number` with a checks dot in the pane header and on the Board; click it for the checks list, Refresh and Open on GitHub. Needs you shows a merge card once checks pass (squash by default) and a "Checks failed" card with "Send to agent".

In the Mac app, Cmd+K also searches messages across all chats (a "Messages" section) and jumps to the hit with a short highlight. Stuck chats get an amber Stuck badge and a Needs you card with Send a nudge and Interrupt; thresholds live in Settings > Stuck chats.

## API overview

All routes need a device token (`Authorization: Bearer <token>` or the `harness_token` cookie), except `GET /api/health` and `POST /api/pairing/redeem`.

| Area | Routes |
|---|---|
| Devices | `POST /api/pairing/codes`, `POST /api/pairing/redeem`, `GET /api/devices`, `DELETE /api/devices/{id}` |
| Repos | `GET/POST /api/repos` (POST body `{path, name?}`: a git work tree root, or any folder outside git as a plain folder; each repo has `git` and `default_branch`, null for plain folders, and `remote_url`, the push URL of `origin` recorded at registration and the only URL an approved push goes to (null for plain folders, or when origin had no single push URL then); registering publishes `repo.added` `{name, repo}`, a `repo.updated` event `{name, repo}` follows when a plain folder becomes a repository, and removing one publishes `repo.removed` `{name}`), `GET/DELETE /api/repos/{name}` (`?purge_sessions=true` also deletes its sessions; the folder is never touched), `GET /api/repos/{name}/link-suggestions`, `PUT /api/repos/{name}/worktree` (`default` true or false overrides the agent default mode for the repo; null follows it), `GET /api/repos/{name}/commands` (slash commands of the repo's latest agent run, for new chats) |
| Sessions | `GET/POST /api/sessions`, `GET/PATCH/DELETE /api/sessions/{id}` (the detail adds `tasks`, `agents` and `background`, the running and completed subagents and background commands, and `queued`, the follow-ups waiting for the turn; every session has `context`, how full the context window is, and `stuck`, `{reason, since, details}` or null), `GET /api/sessions/{id}/events?after=&before=&limit=` (oldest first; with `limit`, the events nearest `before` when given, else nearest `after`, for paging around a search hit), `POST /api/sessions/{id}/messages` (202; while a turn runs the message is queued and `queued_message` is set, and with `interrupt: true` the turn is stopped and the message runs next, ahead of the queue; 409 with `code: "open_in_claude_code"` while Claude Code has the chat open), `DELETE /api/sessions/{id}/queue/{queued_id}`, `POST /api/sessions/{id}/interrupt`, `GET /api/sessions/{id}/commands` (slash commands and agents), `GET /api/sessions/{id}/files?q=` (up to 50 files for @ mentions) |
| Claude Code chats | `GET /api/claude-chats?repo=&include_automated=` (chats of registered repos that harness does not own; automated ones only with `include_automated=true`, each with `entrypoint` and `automated`), `GET /api/claude-chats/{id}`, `GET /api/claude-chats/{id}/events` (read-only history as session events), `POST /api/claude-chats/{id}/adopt` (continue in harness: 201 with the new session, 200 with the existing one), `PUT /api/claude-chats/{id}/archived` (`{archived}`; harness-only, returns the chat; archived chats stay in the list with `archived: true`) |
| Review | `GET /api/sessions/{id}/diff`, `POST /api/sessions/{id}/approve`, `POST /api/sessions/{id}/reject`, `POST /api/sessions/{id}/feedback`. Approve runs git with no hooks; it answers 409 with `code: "unsafe_repo_config"` and `settings` while the repository's own git config sets something that runs a program or sends data elsewhere, and with `code: "remote_not_confirmed"` or `"remote_changed"`, `remote_urls` and `confirmed_url` when origin does not push to the repo's `remote_url` alone; approving again with `confirm_remote_url` (origin's current URL) pushes there and records it (D050); 409 with `code: "unsafe_branch"` and `branch` when an in-place checkout's branch cannot be pushed safely, and 409 when HEAD or a local branch changed since the last audit until `acknowledge_violation` is set (D053); messages sent while approving or merging are queued (202) |
| Approvals | `GET /api/approvals`, `GET /api/approvals/{id}`, `POST /api/approvals/{id}/resolve` (kinds `permission` (payload `{tool, input, title, reason}`, `reason` being Claude Code's reason or null), `question`, `plan` with `decision` `approve` or `keep_planning`, `review`, and `merge`, which only takes `{"dismiss": true}`) |
| Pull requests | `GET /api/prs?repo=&state=open\|merged\|closed\|all` (default open; pull requests harness opened, each `{session_id, repo, session_title, session_state, url, summary, pr}`), `POST /api/sessions/{id}/merge` (`{method: squash\|merge\|rebase, delete_branch}`, defaults squash and true; closes the session and removes its worktree; 502 with `step` and `stderr` when gh fails, 409 without an open pull request or while the agent works), `POST /api/sessions/{id}/pr/refresh` (read it from GitHub now; 502 when gh fails). Every session has `pr` (last known status or null) and `pr_summary` |
| Search | `GET /api/search?q=&repo=&limit=` (`q` 1 to 200 characters, `limit` 1 to 100, default 20): `{hits: [{session_id, repo, title, event_id, ts, kind, snippet}], indexing}`, best match first; `kind` is `title`, `user`, `assistant`, `tool`, `tool_result` or `claude_chat` (then `session_id` is the Claude Code chat id); `event_id` is null for titles; matches in `snippet` are wrapped in `[[` and `]]` |
| Stuck | `GET/PUT /api/stuck/settings` (`{waiting_minutes, silent_minutes, repeated_calls, turn_minutes}`); events `session.stuck` `{reason: waiting\|silent\|repeating\|long_turn, since, details}` and `session.unstuck` `{reason}`; `notify` kind `stuck` |
| Models and defaults | `GET /api/models` (`{models: [{value, display_name, description, effort_levels, supports_effort}], updated_at}` in Claude Code's order; `updated_at` null for the built-in aliases), `GET /api/account` (`{display_name, email, plan, organization}`, each nullable), `GET/PUT /api/agents/defaults` (`{model, effort, permission_mode, mode: in_place\|worktree}`; 422 when the model does not take the effort) |
| Attachments | `POST /api/attachments` |
| Organize | `PATCH /api/sessions/{id}` (title, pinned, archived, model, permission mode, effort; a new effort applies from the next message), `DELETE /api/sessions/{id}?purge=true`, `GET /api/sessions?repo=&archived=` |
| Notifications | `GET /api/push/vapid-key`, `POST/DELETE /api/push/subscribe` (the caller's own subscriptions), `POST /api/push/test`, `GET/PUT /api/notifications/settings` |
| Connectors and usage | `GET /api/connectors`, `GET /api/usage/month?year=&month=` (probe tokens apart in `probes`), `GET /api/usage/limits`, `POST /api/usage/refresh` (429 with `Retry-After` within 20 s of the last probe, 502 when Claude reports nothing), `GET/PUT /api/usage/settings`, `POST /api/clients/visibility` |
| Local apps | `POST /api/sessions/{id}/open-in-claude-code`, `POST /api/repos/{name}/open` (`vscode`, `finder`, `terminal`) |
| Events | `WS /api/events?after=<id>` (replay, then live; text deltas, `session.thinking`, `claude_chats.updated` and live `session.agents` updates during a turn arrive with `id: null`; revoking a device closes its sockets with 4401; `session.notice` `{kind: compacted\|cleared\|model_fallback\|api_retry, text}` marks Claude Code's own notices; a turn that ends with an engine error ends with `session.state` `failed` and its reason) |

Coverage is enforced at 100%: daemon line and branch coverage, web lines, branches, functions and statements, and `HarnessKit` lines and functions.

## License

[MIT](LICENSE)
