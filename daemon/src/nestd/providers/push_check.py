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


def gh_refusal(args: Sequence[str]) -> str | None:
    """Why Nest's `gh` refuses `gh <args>`; None runs it."""
    command = next((arg for arg in args if not arg.startswith("-")), None)
    if command is not None and command not in GH_COMMANDS:
        return f"{DENY_REASON} (gh {command} is not one of gh's own commands)"
    return DENY_REASON if is_git_write(shlex.join(["gh", *args])) else None


def hook_answer(event: object) -> dict[str, object] | None:
    """The deny for a subagent's tool call that pushes or writes a pull request."""
    if not isinstance(event, dict) or "agent_id" not in event:
        return None
    fields = cast(dict[str, object], event)
    tool, tool_input = fields.get("tool_name"), fields.get("tool_input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        return None
    if not tool_writes(tool, cast(dict[str, object], tool_input)):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_REASON,
        }
    }


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
                return 0
            answer = hook_answer(event)
            if answer is not None:
                json.dump(answer, stdout)
            return 0
        case _:
            print("usage: push_check gh <args> | hook", file=stderr)
            return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdin, sys.stdout, sys.stderr))
