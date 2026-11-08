"""The checks behind Nest's helper scripts (`push_block`), run as
`python -I -m nestd.providers.push_check gh <args>` by its `gh` (exit 1 refuses, with the
reason on stderr) and `... hook` by Codex's PreToolUse hook for a chat's subagents (the
hook event on stdin, a deny on stdout). Only the command checks are imported, so it starts
fast.
"""

import json
import shlex
import sys
from collections.abc import Sequence
from typing import TextIO, cast

from nestd.providers.git_commands import is_git_write
from nestd.providers.git_tools import DENY_REASON, tool_writes

# gh's own commands and help topics (gh 2.93.0's `gh help`); any other word is an alias
# or an extension, which Nest cannot read.
GH_COMMANDS = frozenset(
    {
        *("agent-task", "alias", "api", "attestation", "auth", "browse", "cache"),
        *("codespace", "completion", "config", "copilot", "extension", "gist", "gpg-key"),
        *("help", "issue", "label", "licenses", "org", "pr", "preview", "project"),
        *("release", "repo", "ruleset", "run", "search", "secret", "skill", "ssh-key"),
        *("status", "variable", "version", "workflow"),
        *("accessibility", "actions", "environment", "exit-codes", "formatting"),
        *("mintty", "reference", "telemetry"),
    }
)

_ROOT_FLAGS = frozenset({"--help", "-h", "--version"})
# gh's commands that run code or an agent with the user's login, by the actions that only
# read: the rest could push or open a pull request themselves (`agent-task create`, a
# command run in a codespace, an extension, Copilot).
_RUNS_CODE: dict[str, frozenset[str | None]] = {
    "agent-task": frozenset({"list", "view", None}),
    "codespace": frozenset({"list", "view", "logs", "ports", None}),
    "copilot": frozenset(),
    "extension": frozenset({"list", "ls", "search", None}),
}


def gh_refusal(args: Sequence[str]) -> str | None:
    """Why Nest's `gh` refuses `gh <args>`; None runs it. gh takes no flags before its
    command but help and version, so a flag there could hide which command runs.
    """
    at = next((i for i, arg in enumerate(args) if not arg.startswith("-")), len(args))
    if any(flag not in _ROOT_FLAGS for flag in args[:at]):
        return f"{DENY_REASON} (Nest reads no flag before gh's command)"
    command = args[at] if at < len(args) else None
    if command is not None and command not in GH_COMMANDS:
        return f"{DENY_REASON} (gh {command} is not one of gh's own commands)"
    action = next((arg for arg in args[at + 1 :] if not arg.startswith("-")), None)
    if command in _RUNS_CODE and action not in _RUNS_CODE[command]:
        return f"{DENY_REASON} (gh {command} can run code with the user's login)"
    return DENY_REASON if is_git_write(shlex.join(["gh", *args])) else None


# What Codex's PreToolUse hook answers to refuse a call (Claude's form).
DENY: dict[str, object] = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": DENY_REASON,
    }
}


def hook_answer(event: object) -> dict[str, object] | None:
    """The deny for a subagent's tool call that pushes or writes a pull request. Only a
    subagent's events come here, so one that cannot be read is refused.
    """
    if not isinstance(event, dict):
        return DENY
    fields = cast(dict[str, object], event)
    if "agent_id" not in fields:
        return None
    tool, tool_input = fields.get("tool_name"), fields.get("tool_input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        return None
    if not tool_writes(tool, cast(dict[str, object], tool_input)):
        return None
    return DENY


def main(argv: Sequence[str], stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    match argv:
        case ["gh", *args]:
            reason = gh_refusal(args)
            if reason is not None:
                print(reason, file=stderr)
                return 1
            return 0
        case ["hook"]:
            try:
                event: object = json.load(stdin)
            except ValueError:
                event = None
            answer = hook_answer(event)
            if answer is not None:
                json.dump(answer, stdout)
            return 0
        case _:
            print("usage: push_check gh <args> | hook", file=stderr)
            return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdin, sys.stdout, sys.stderr))
