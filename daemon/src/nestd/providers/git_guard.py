"""Layers 1 and 2 of the agent git block (D013, D049): permission rules and a PreToolUse hook.
Pixie chats, habit runs and chats a pixie started keep the block; other chats do not (B58).

The hook runs for every tool, not only Bash. It denies:
- a tool whose input holds a command line (`command`, `cmd`, `script`, `shell_command`,
  `command_line`, as a string or an argv list) or an argv list (`args`, `argv`) that
  `is_git_write` flags, such as Bash, the CLI's Monitor tool or Serena's
  `execute_shell_command`;
- an MCP tool whose own name opens or merges a pull request, pushes or commits, such as
  GitHub's `create_pull_request`, `merge_pull_request`, `push_files` and
  `create_or_update_file`, or a git server's `git_commit` and `git_push`.

Other tools pass untouched, even when their text mentions git (Edit, Write, Skill).
"""

import re
import shlex
from collections.abc import Iterator, Mapping

from claude_agent_sdk.types import HookContext, HookInput, HookJSONOutput

from nestd.providers.git_commands import is_git_write

__all__ = ["DENY_REASON", "GIT_WRITE_RULES", "block_git_writes", "is_git_write", "tool_writes"]

GIT_WRITE_RULES = (
    "Bash(git commit:*)",
    "Bash(git push:*)",
    "Bash(gh pr create:*)",
    "Bash(gh pr merge:*)",
)
DENY_REASON = "Nest: commits, pushes and pull requests are made by Nest after you approve them"

# Input keys, lowercased without separators, that hold a command line or an argv list.
_COMMAND_KEYS = frozenset({"command", "cmd", "script", "shellcommand", "commandline"})
_ARGV_KEYS = frozenset({"args", "argv"})
_MCP_PREFIX = "mcp__"
_MCP_GIT_WRITE = re.compile(
    r"(?:create|merge)pullrequest|pushfiles|createorupdatefile|gitcommit|gitpush|createcommit"
)


def tool_writes(tool_name: str, tool_input: Mapping[str, object]) -> bool:
    if tool_name.startswith(_MCP_PREFIX):
        own_name = tool_name.rsplit("__", 1)[-1]
        if _MCP_GIT_WRITE.search(_letters(own_name)):
            return True
    return any(is_git_write(command) for command in _command_lines(tool_input))


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


async def block_git_writes(
    input_data: HookInput, tool_use_id: str | None, context: HookContext
) -> HookJSONOutput:
    """PreToolUse hook for every tool that denies commits, pushes and PR writes."""
    if input_data["hook_event_name"] != "PreToolUse":
        return {}
    if not tool_writes(input_data["tool_name"], input_data["tool_input"]):
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_REASON,
        }
    }
