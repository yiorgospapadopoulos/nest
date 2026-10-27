"""Nest's permission modes as Codex's approval policy, reviewer and sandbox (B91, D113).

| Nest mode         | approval policy | sandbox            | reviewer    |
|-------------------|-----------------|--------------------|-------------|
| default (or none) | untrusted       | workspace-write    | user        |
| acceptEdits       | untrusted       | workspace-write    | user        |
| plan              | never           | read-only          | user        |
| auto              | on-request      | workspace-write    | auto_review |
| bypassPermissions | never           | danger-full-access | user        |

In acceptEdits Nest accepts file changes itself and asks for commands. Every sandbox has
network, as Claude Code has.

`untrusted` asks before every command Codex does not know to be read-only and before every
file change, as Claude Code's default mode asks. A guarded run (D013, B58: pixie chats,
habit runs, chats a pixie started, called pixies) gets no sandbox beyond Claude's (B112):
always `untrusted` with the user as reviewer and full access (read-only in plan mode, which
is what the mode is), so every such command and file change comes to Nest, which declines
git writes; in bypass Nest accepts the rest itself. A run with a write root (a pixie's,
D072) is also `untrusted`, so each file change comes to Nest, which declines one outside the
root (`codex_approvals`), as Claude's write guard denies it.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from nestd.config.models import PermissionMode
from nestd.providers.git_commands import is_git_write

type ApprovalPolicy = Literal["untrusted", "on-request", "never"]
type SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
type Reviewer = Literal["user", "auto_review"]
type AutoDecision = Literal["accept", "decline"]


@dataclass(frozen=True)
class CodexPermissions:
    approval_policy: ApprovalPolicy
    sandbox: SandboxMode
    reviewer: Reviewer
    network: bool

    def sandbox_policy(self, writable_roots: Sequence[Path]) -> dict[str, JsonValue]:
        """The turn's `sandboxPolicy`: `writable_roots` beside the working directory."""
        if self.sandbox == "danger-full-access":
            return {"type": "dangerFullAccess"}
        if self.sandbox == "read-only":
            return {"type": "readOnly", "networkAccess": self.network}
        return {
            "type": "workspaceWrite",
            "writableRoots": [str(root) for root in writable_roots],
            "networkAccess": self.network,
            "excludeTmpdirEnvVar": False,
            "excludeSlashTmp": False,
        }


_MODES: dict[PermissionMode, CodexPermissions] = {
    "default": CodexPermissions("untrusted", "workspace-write", "user", network=True),
    "acceptEdits": CodexPermissions("untrusted", "workspace-write", "user", network=True),
    "plan": CodexPermissions("never", "read-only", "user", network=True),
    "auto": CodexPermissions("on-request", "workspace-write", "auto_review", network=True),
    "bypassPermissions": CodexPermissions("never", "danger-full-access", "user", network=True),
}


def codex_permissions(
    mode: PermissionMode | None, guarded: bool, write_root: Path | None = None
) -> CodexPermissions:
    """A guarded run or one with a `write_root` asks Nest about every command Codex does
    not know to be read-only and every file change.
    """
    if guarded:
        sandbox: SandboxMode = "read-only" if mode == "plan" else "danger-full-access"
        return CodexPermissions("untrusted", sandbox, "user", network=True)
    permissions = _MODES[mode or "default"]
    if write_root is None:
        return permissions
    return replace(permissions, approval_policy="untrusted", reviewer="user")


def command_decision(
    command: str, mode: PermissionMode | None, guarded: bool
) -> AutoDecision | None:
    """What Nest answers a command approval itself; None asks the user."""
    if guarded and is_git_write(command):
        return "decline"
    if mode == "bypassPermissions":
        return "accept"
    return None


def file_change_decision(mode: PermissionMode | None) -> AutoDecision | None:
    """What Nest answers a file change approval itself; None asks the user. Plan mode
    edits nothing, as Claude Code's plan mode.
    """
    if mode in ("acceptEdits", "bypassPermissions"):
        return "accept"
    if mode == "plan":
        return "decline"
    return None
