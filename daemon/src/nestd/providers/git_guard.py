"""The agent git block while the user has not let agents push (D013, D049, D160): permission
rules and a PreToolUse hook on Claude, and on every engine a git-level block in the
environment of a run with its own process (`NO_PUSH_ENV`).
Pixie chats, habit runs, chats a pixie started and Autopilot are blocked whole. Any other
chat is blocked only in its subagents, and only on Claude (B58, B127): Codex declines what
they ask Nest about, which it does not do in every mode, and ACP has no such block. The block
covers pushes, pull requests and `gh` writes; commits are allowed (D123), and the user's login
stays, so fetch, pull and `gh` reads work.

The hook runs for every tool, not only Bash. It denies:
- a tool whose input holds a command line (`command`, `cmd`, `script`, `shell_command`,
  `command_line`, as a string or an argv list) or an argv list (`args`, `argv`) that
  `is_git_write` flags, such as Bash, the CLI's Monitor tool or Serena's
  `execute_shell_command`;
- an MCP tool whose own name opens or merges a pull request or writes to a remote, such
  as GitHub's `create_pull_request`, `merge_pull_request`, `push_files`,
  `create_or_update_file` and `create_commit`, or a git server's `git_push`.

Other tools pass untouched, even when their text mentions git (Edit, Write, Skill).
"""

import re
import shlex
from collections.abc import Iterator, Mapping

from claude_agent_sdk.types import HookCallback, HookContext, HookInput, HookJSONOutput

from nestd.providers.git_commands import is_git_write

__all__ = [
    "DENY_REASON",
    "GIT_WORKTREE_RULES",
    "GIT_WRITE_RULES",
    "NO_PUSH_ENV",
    "WORKTREE_DENY_REASON",
    "block_autopilot_git",
    "block_git_writes",
    "block_subagent_git_writes",
    "block_worktree_removal",
    "is_git_write",
    "tool_writes",
]

GIT_WRITE_RULES = (
    "Bash(git push:*)",
    "Bash(gh pr create:*)",
    "Bash(gh pr merge:*)",
)
# Also blocked with `guard_worktrees` (Autopilot).
GIT_WORKTREE_RULES = ("Bash(git worktree remove:*)",)
DENY_REASON = (
    "Nest: pixies and subagents may commit, but pushing, opening or merging pull requests and "
    "writing to GitHub with gh are off in the user's settings"
)
AUTOPILOT_DENY_REASON = (
    "Nest: Autopilot leaves pushes, pull requests and removing worktrees to the user"
)
WORKTREE_DENY_REASON = "Nest: Autopilot leaves removing worktrees to the user"

# git rewrites every remote's push address to one no helper answers, so `git push` fails even
# from a script, while fetch and pull work: an empty pushInsteadOf matches any URL. Known gaps
# in a script: git does not rewrite a remote's own explicit `pushurl`, so that remote has only
# the checks above (clearing origin's would make git list a phantom `origin` and break
# `git fetch --all` without one); the user's own longer pushInsteadOf rule; and `git send-pack`
# with a URL. `gh` cannot be split this way, so pull requests have only the checks above.
NO_PUSH_ENV = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "url.nest-pushing-is-off://.pushInsteadOf",
    "GIT_CONFIG_VALUE_0": "",
}

# Input keys, lowercased without separators, that hold a command line or an argv list.
_COMMAND_KEYS = frozenset({"command", "cmd", "script", "shellcommand", "commandline"})
_ARGV_KEYS = frozenset({"args", "argv"})
_MCP_PREFIX = "mcp__"
_MCP_GIT_WRITE = re.compile(
    r"(?:create|merge)pullrequest|pushfiles|createorupdatefile|gitpush|createcommit"
)


def tool_writes(
    tool_name: str,
    tool_input: Mapping[str, object],
    *,
    pushes: bool = True,
    worktrees: bool = False,
) -> bool:
    if pushes and tool_name.startswith(_MCP_PREFIX):
        own_name = tool_name.rsplit("__", 1)[-1]
        if _MCP_GIT_WRITE.search(_letters(own_name)):
            return True
    return any(
        is_git_write(c, pushes=pushes, worktrees=worktrees) for c in _command_lines(tool_input)
    )


def _command_lines(tool_input: Mapping[str, object]) -> Iterator[str]:
    for key, value in tool_input.items():
        name = _letters(key)
        if name in _COMMAND_KEYS and isinstance(value, str):
            yield value
        elif name in _COMMAND_KEYS | _ARGV_KEYS and isinstance(value, list):
            words: list[object] = value  # pyright: ignore[reportUnknownVariableType]
            yield shlex.join(word for word in words if isinstance(word, str))


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def _denying(reason: str, *, pushes: bool = True, worktrees: bool = False) -> HookCallback:
    """A PreToolUse hook for every tool that denies what `tool_writes` flags."""

    async def guard(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if input_data["hook_event_name"] != "PreToolUse":
            return {}
        tool, tool_input = input_data["tool_name"], input_data["tool_input"]
        if not tool_writes(tool, tool_input, pushes=pushes, worktrees=worktrees):
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    return guard


block_git_writes = _denying(DENY_REASON)
block_autopilot_git = _denying(AUTOPILOT_DENY_REASON, worktrees=True)
block_worktree_removal = _denying(WORKTREE_DENY_REASON, pushes=False, worktrees=True)


async def block_subagent_git_writes(
    input_data: HookInput, tool_use_id: str | None, context: HookContext
) -> HookJSONOutput:
    """As `block_git_writes` for any subagent of a run, a pixie or not: the chat itself may
    push when asked (B127). `agent_type` also names the main agent of an `--agent` session,
    so only `agent_id` tells a subagent.
    """
    if "agent_id" not in input_data:
        return {}
    return await block_git_writes(input_data, tool_use_id, context)
