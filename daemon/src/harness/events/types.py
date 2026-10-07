"""Event type names. Clients filter on these strings, so treat them as a wire contract."""

from typing import Final

DAEMON_STARTED: Final = "daemon.started"
DEVICE_PAIRED: Final = "device.paired"
DEVICE_REVOKED: Final = "device.revoked"

# A repo was unregistered (its config deleted); global, the payload names it.
REPO_REMOVED: Final = "repo.removed"
# A repo's config changed on its own, such as a plain folder that became a git repository
# (D041); global, `{name, repo}` with the whole repo. Clients replace their copy.
REPO_UPDATED: Final = "repo.updated"

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
SESSION_RESULT: Final = "session.result"
SESSION_GIT_VIOLATION: Final = "session.git_violation"
# Not a session event (its events are deleted with it): the payload names the session.
SESSION_DELETED: Final = "session.deleted"
# Snapshots of the agent's task list and of its agents (main and subagents).
SESSION_TASKS: Final = "session.tasks"
SESSION_AGENTS: Final = "session.agents"
# A subagent or background command the engine runs as a task started, moved to the
# background or finished; stored, possibly between turns. Tracking reads it.
SESSION_AGENT_TASK: Final = "session.agent_task"
# The session's queued follow-up messages after any change, oldest first (D032).
SESSION_QUEUED: Final = "session.queued"
# How full the agent's context window is, after each turn (D032).
SESSION_CONTEXT: Final = "session.context"
# The session's pull request status on GitHub changed (D034): `{pr}`.
SESSION_PR: Final = "session.pr"
# The session looks stuck, `{reason, since, details}` as in the session's `stuck`, or no
# longer does, `{reason}` of the flag that cleared (D036).
SESSION_STUCK: Final = "session.stuck"
SESSION_UNSTUCK: Final = "session.unstuck"

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
