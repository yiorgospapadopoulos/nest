"""Event type names. Clients filter on these strings, so treat them as a wire contract."""

from typing import Final

DAEMON_STARTED: Final = "daemon.started"
DEVICE_PAIRED: Final = "device.paired"
DEVICE_REVOKED: Final = "device.revoked"

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
SESSION_RESULT: Final = "session.result"
SESSION_GIT_VIOLATION: Final = "session.git_violation"
# Not a session event (its events are deleted with it): the payload names the session.
SESSION_DELETED: Final = "session.deleted"
# Snapshots of the agent's task list and of its agents (main and subagents).
SESSION_TASKS: Final = "session.tasks"
SESSION_AGENTS: Final = "session.agents"

# The approval queue; each carries the full item and its session id.
APPROVAL_CREATED: Final = "approval.created"
APPROVAL_RESOLVED: Final = "approval.resolved"

# Git actions the daemon performs after the user approves a session's work.
GIT_COMMITTED: Final = "git.committed"
GIT_PUSHED: Final = "git.pushed"
GIT_FAILED: Final = "git.failed"
PR_OPENED: Final = "pr.opened"

# Something the user should hear about; delivery channels subscribe to these.
NOTIFY: Final = "notify"

# The connectors list (MCP servers and claude.ai connectors) after a status changed; global.
CONNECTORS_UPDATED: Final = "connectors.updated"

# Subscription usage windows reported by the agent engine; global, not per session.
USAGE_UPDATED: Final = "usage.updated"
