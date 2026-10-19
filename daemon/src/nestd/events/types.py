"""Event type names. Clients filter on these strings, so treat them as a wire contract."""

from typing import Final

DEVICE_REVOKED: Final = "device.revoked"

# A repo was registered; global, `{name, repo}` as in REPO_UPDATED. Clients add it.
REPO_ADDED: Final = "repo.added"
# A repo was unregistered (its config deleted); global, the payload names it.
REPO_REMOVED: Final = "repo.removed"
# A repo's config changed on its own, such as a plain folder that became a git repository
# (D041); global, `{name, repo}` with the whole repo. Clients replace their copy.
REPO_UPDATED: Final = "repo.updated"
# The user reordered the projects (D090); global, `{order}` with every repo's name in the
# new order. Clients sort their list by it.
REPOS_REORDERED: Final = "repos.reordered"

# Agent sessions; all carry the session id. SESSION_DELTA is ephemeral (never stored).
SESSION_CREATED: Final = "session.created"
# Renamed, pinned, archived or new controls; carries the changed fields and the session.
SESSION_UPDATED: Final = "session.updated"
SESSION_STATE: Final = "session.state"
SESSION_WORKSPACE: Final = "session.workspace"
SESSION_SETUP_FAILED: Final = "session.setup_failed"
SESSION_USER_MESSAGE: Final = "session.user_message"
SESSION_MESSAGE: Final = "session.message"
SESSION_DELTA: Final = "session.delta"
# The main agent started (`{active: true}`) or finished a thinking block; ephemeral (D045).
SESSION_THINKING: Final = "session.thinking"
# Thinking text as it is written, `{text, parent_tool_use_id}` (null for the main agent);
# ephemeral, the finished block arrives in a SESSION_MESSAGE (B59).
SESSION_THINKING_DELTA: Final = "session.thinking_delta"
# A subagent's text as it is written, `{text, parent_tool_use_id}` naming the Agent call
# that started it; ephemeral, like SESSION_DELTA for the main agent (B59).
SESSION_SUBAGENT_DELTA: Final = "session.subagent_delta"
# A hook from the user's setup finished with something to show (B59): `{hook_id,
# hook_name, hook_event, outcome, exit_code, system_message, output}`; stored, also
# between turns.
SESSION_HOOK: Final = "session.hook"
SESSION_RESULT: Final = "session.result"
# A note for the transcript, `{kind, text}`: compacted, cleared, model_fallback or
# api_retry (the first of a turn). Clients show the text as a muted line.
SESSION_NOTICE: Final = "session.notice"
# Not a session event (its events are deleted with it): the payload names the session.
SESSION_DELETED: Final = "session.deleted"
# Snapshots of the agent's task list and of its agents (main and subagents).
SESSION_TASKS: Final = "session.tasks"
SESSION_AGENTS: Final = "session.agents"
# A subagent or background command the engine runs as a task started, moved to the
# background or finished; stored, possibly between turns. Tracking reads it.
SESSION_AGENT_TASK: Final = "session.agent_task"
# The session's queued follow-up messages after any change, oldest first (D032); those
# written into the running turn are `sent` until the agent reads them (B59).
SESSION_QUEUED: Final = "session.queued"
# The conversation was rewound to before the user message of event `message` (B59): the
# session's events `message` to `through` are deleted; clients drop them too. Events after
# `through` (what the cut run said as it opened) stay. `{message, through, text,
# attachments}`, the message for the composer.
SESSION_REWOUND: Final = "session.rewound"
# How full the agent's context window is, after each turn (D032).
SESSION_CONTEXT: Final = "session.context"
# The session's pull request status on GitHub changed (D034): `{pr}`.
SESSION_PR: Final = "session.pr"
# The session looks stuck, `{reason, since, details}` as in the session's `stuck`, or no
# longer does, `{reason}` of the flag that cleared (D036).
SESSION_STUCK: Final = "session.stuck"
SESSION_UNSTUCK: Final = "session.unstuck"
# The chat paused at the usage limit, `{limit_pause}` as in the session's `limit_pause`
# (B78); its messages wait until the daemon goes on at `resume_at`. The pause cleared,
# `{reason}`: `reset` (the daemon goes on), `resumed` (Resume now or Send now), `stopped`
# (the user's Stop), `archived` or `closed`. Both follow the `session.updated` of the field.
SESSION_LIMIT_PAUSED: Final = "session.limit_paused"
SESSION_LIMIT_CLEARED: Final = "session.limit_cleared"

# The approval queue; each carries the full item and its session id.
APPROVAL_CREATED: Final = "approval.created"
APPROVAL_RESOLVED: Final = "approval.resolved"

# Git actions the daemon performs after the user approves a session's work.
GIT_COMMITTED: Final = "git.committed"
GIT_PUSHED: Final = "git.pushed"
GIT_FAILED: Final = "git.failed"
PR_OPENED: Final = "pr.opened"
# The daemon merged the session's pull request after the user approved: `{url, method}`.
PR_MERGED: Final = "pr.merged"

# Something the user should hear about; delivery channels subscribe to these.
NOTIFY: Final = "notify"

# The connectors list (MCP servers and claude.ai connectors) after a status changed; global.
CONNECTORS_UPDATED: Final = "connectors.updated"

# The Claude Code chats of some repos changed (new, updated, adopted, archived, opened or
# closed in Claude Code); ephemeral and global, the payload names the repos. Clients list
# them again.
CLAUDE_CHATS_UPDATED: Final = "claude_chats.updated"

# Subscription usage windows reported by the agent engine; global, not per session.
USAGE_UPDATED: Final = "usage.updated"
# A usage window first reached `[usage] warn_percent` in its period (D104); global,
# `{window: "five_hour" | "seven_day", utilization (0 to 1), resets_at}`.
USAGE_WARNING: Final = "usage.warning"

# Pixies (D072); global. A pixie was created or changed, `{pixie}` with the whole pixie,
# or deleted, `{pixie_id}`. Clients replace or drop their copy.
PIXIE_UPDATED: Final = "pixie.updated"
PIXIE_DELETED: Final = "pixie.deleted"
# Pixie teams (B40); global. A team was created or changed (a new leader too), `{team}`
# with the whole team, or deleted, `{id}`; its pixies are announced first, without it.
PIXIE_TEAM_UPDATED: Final = "pixie_team.updated"
PIXIE_TEAM_DELETED: Final = "pixie_team.deleted"
# A card in a pixie's chat, stored as one of its session events (B41): `{kind, session_id}`.
# `session`: a chat the pixie started, shown with its live state; `pr`: that chat's pull
# request, shown with its checks and review state. Clients render both from their stores.
# B42 adds `{kind: "report", report_id}`, `{kind: "choices", options}` (reply buttons) and
# `{kind: "habit_suggestion", habit: {name, prompt, schedule, triggers}}`.
PIXIE_CARD: Final = "pixie.card"
# A pixie reported something (B42), `{report}` with the whole report; global. Read reports
# follow as `{ids}`.
PIXIE_REPORT: Final = "pixie.report"
PIXIE_REPORT_READ: Final = "pixie.report_read"
# Pixie habits (B42); global. A habit was created or changed, or its runs moved its last
# run or next due time, `{habit}` with the whole habit; or deleted, `{id, pixie_id}`. A
# run's outcome changed (queued, running, then how it ended), `{run}`.
HABIT_UPDATED: Final = "habit.updated"
HABIT_DELETED: Final = "habit.deleted"
HABIT_RUN_UPDATED: Final = "habit.run_updated"

# The pixies a project chat called, as its group (B46): `{group}`, its solo pixies and
# teams as `GET /api/sessions/{id}/pixies` lists them; after a call starts, changes state
# or continues, and after Send away. Stored.
SESSION_PIXIES: Final = "session.pixies"

# Settings (D104); all global. The Claude account after a sign in, sign out or a failed
# sign in: `GET /api/accounts/claude`'s body plus `error` (null unless it failed).
ACCOUNT_CLAUDE: Final = "account.claude"
# Installing Claude Code: `{state: "running" | "done" | "failed", message}`, then the new
# `GET /api/claude-code` body as CLAUDE_CODE_UPDATED.
CLAUDE_CODE_INSTALL: Final = "claude_code.install"
CLAUDE_CODE_UPDATED: Final = "claude_code.updated"
# Plugins or marketplaces changed through Nest, `{}`; clients list them again.
EXTENSIONS_UPDATED: Final = "extensions.updated"
# Artifacts (B79). The chat's agent saved one, at that place in its transcript (stored):
# `{artifact_id, version, title, kind, action}`, `action` `created` or `updated`, or
# `edited` when the user saved a document section in the reader (B88).
SESSION_ARTIFACT: Final = "session.artifact"
# Global, each with `unseen`, the count of artifacts whose latest version is not opened
# yet. Saved: `{artifact, action, version, unseen}` with the whole artifact. Seen (opened
# while unseen) or deleted: `{artifact_id, unseen}`.
ARTIFACT_SAVED: Final = "artifact.saved"
ARTIFACT_SEEN: Final = "artifact.seen"
ARTIFACT_DELETED: Final = "artifact.deleted"
# Ephemeral (B88): what an artifact's page stores changed, `{artifact_id, set, remove, clear,
# client}` with the new values, so the user's other open pages stay in step; `client` is
# the writer's own id, if it sent one, so it can skip its echo.
ARTIFACT_STORAGE: Final = "artifact.storage"
# Ephemeral (B88): an artifact's page asked Claude, `{artifact_id, state, remaining, limit}`,
# `state` `started` or `finished`, `remaining` the asks it has left today of `limit` a day;
# readers show it working.
ARTIFACT_ASK: Final = "artifact.ask"
