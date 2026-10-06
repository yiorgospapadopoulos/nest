"""Layers 1 and 2 of the agent git block (D013): permission rules and a PreToolUse hook.

The hook matches `commit` or `push` in git's subcommand position, after any global options
(`-c k=v`, `-C dir`, `--git-dir x`, `--no-pager`), anywhere in the command line, so shell
wrappers (`sh -c '...'`, `cd x && ...`, `xargs`, `$(...)`) are caught. It also matches
`gh pr create` and `gh pr merge`.

Accepted false positives: commands that merely mention a blocked command, such as
`echo "git commit"` or `grep "git push" docs`; and `git commit-tree`.
Known false negatives: git aliases (`git ci`), commands assembled from variables or
scripts the agent writes. Layer 4 (the daemon's ref audit after each turn) catches those.
Read-only commands that mention the words elsewhere (`git log --grep commit`,
`git diff src/commit.ts`, `git stash push`) are allowed.
"""

import re

from claude_agent_sdk.types import HookContext, HookInput, HookJSONOutput

GIT_WRITE_RULES = (
    "Bash(git commit:*)",
    "Bash(git push:*)",
    "Bash(gh pr create:*)",
    "Bash(gh pr merge:*)",
)
DENY_REASON = (
    "harness: commits, pushes and pull requests are made by harness after you approve them"
)

_GIT_OPTION = r"(?:-[cC]\s+\S+|--(?:git-dir|work-tree|namespace|config-env)\s+\S+|-\S+)"
_GIT_WRITE = re.compile(rf"\bgit(?:\s+{_GIT_OPTION})*\s+[\"']?(?:commit|push)\b")
_GH_PR_WRITE = re.compile(r"\bgh\s+pr\s+[\"']?(?:create|merge)\b")


def is_git_write(command: str) -> bool:
    return bool(_GIT_WRITE.search(command) or _GH_PR_WRITE.search(command))


async def block_git_writes(
    input_data: HookInput, tool_use_id: str | None, context: HookContext
) -> HookJSONOutput:
    """PreToolUse hook for the Bash tool that denies commits, pushes and PR writes."""
    if input_data["hook_event_name"] != "PreToolUse":
        return {}
    command = input_data["tool_input"].get("command")
    if not isinstance(command, str) or not is_git_write(command):
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_REASON,
        }
    }
