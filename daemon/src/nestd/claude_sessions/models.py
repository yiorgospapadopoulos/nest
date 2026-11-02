from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

type ChatEngine = Literal["claude", "codex"]


class ClaudeChat(BaseModel):
    """A Claude Code or Codex chat of a registered repo that Nest does not own (yet)."""

    # Claude Code's session id, which `claude --resume` and the SDK's resume take, or
    # Codex's thread id.
    id: str
    repo: str
    title: str
    # Where the chat ran: the repo folder or one of its worktrees.
    cwd: Path
    # The name of that worktree's folder (`<repo>/.claude/worktrees/<name>`, or for Codex
    # any git worktree of the repo), if any.
    worktree: str | None
    created_at: datetime
    # The transcript file's last change; Codex's own last update of the thread.
    last_activity_at: datetime
    # User prompts and assistant replies with text.
    message_count: int
    # A Claude Code process has the chat open right now (`~/.claude/sessions`); always
    # false for Codex.
    open_in_claude_code: bool
    # What started the chat, as Claude Code recorded it (`cli`, `claude-desktop`, `sdk-py`),
    # or Codex's source (`cli`, `vscode`, `exec`, `appServer`, `unknown`, `custom`).
    entrypoint: str | None
    # Started by a program, not typed by the user: through an Agent SDK (entrypoint
    # `sdk-*`), or for Codex any source but `cli` and `vscode`, or Nest's own.
    automated: bool
    # Archived in Nest (D040), or for Codex in Codex itself (B113); clients show it in
    # their Archived group.
    archived: bool = False
    engine: ChatEngine = "claude"


class SetChatArchived(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archived: bool
