from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ClaudeChat(BaseModel):
    """A Claude Code chat of a registered repo that harness does not own (yet)."""

    # Claude Code's session id, which `claude --resume` and the SDK's resume take.
    id: str
    repo: str
    title: str
    # Where the chat ran: the repo folder or one of Claude Code's worktrees in it.
    cwd: Path
    # The name of that Claude Code worktree (`<repo>/.claude/worktrees/<name>`), if any.
    worktree: str | None
    created_at: datetime
    # The transcript file's last change.
    last_activity_at: datetime
    # User prompts and assistant replies with text.
    message_count: int
    # A Claude Code process has the chat open right now (`~/.claude/sessions`).
    open_in_claude_code: bool
    # What started the chat, as Claude Code recorded it (`cli`, `claude-desktop`, `sdk-py`).
    entrypoint: str | None
    # Started by a program through an Agent SDK (entrypoint `sdk-*`), not typed by the user.
    automated: bool
    # Archived in harness (D040); clients show it in their Archived group.
    archived: bool = False


class SetChatArchived(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archived: bool
