"""Whether a tool call pushes, opens or merges a pull request, or writes to GitHub (D049,
D160), for the hooks and approvals of every engine. Kept apart from the Claude hooks
(`git_guard`) so Nest's helper scripts (`push_check`) start fast.

A tool call writes when:
- its input holds a command line (`command`, `cmd`, `script`, `shell_command`,
  `command_line`, as a string or an argv list) or an argv list (`args`, `argv`) that
  `is_git_write` flags, such as Bash, the CLI's Monitor tool or Serena's
  `execute_shell_command`;
- it is an MCP tool whose own name opens or merges a pull request or writes to a remote,
  such as GitHub's `create_pull_request`, `merge_pull_request`, `push_files`,
  `create_or_update_file` and `create_commit`, or a git server's `git_push`.

Other tools pass untouched, even when their text mentions git (Edit, Write, Skill).
"""

import re
import shlex
from collections.abc import Iterator, Mapping

from nestd.providers.git_commands import is_git_write

DENY_REASON = (
    "Nest: pixies and subagents may commit, but pushing, opening or merging pull requests and "
    "writing to GitHub with gh are off in the user's settings"
)

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
