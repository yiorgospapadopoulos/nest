"""The agent git block while the user has not let agents push (D013, D049, D160) on
Claude: permission rules and a PreToolUse hook for every tool that denies what
`tool_writes` flags. A guarded run's own programs get the git-level block and Nest's `gh`
(`push_block`) on every engine.
Pixie chats, habit runs, chats a pixie started and Autopilot are blocked whole. Any other
chat is blocked only in its subagents (B58, B127): on Claude by this hook, on Codex by its
own PreToolUse hook (`push_block.subagent_hook_args`), on OpenCode and Gemini by their own
rules for subagents (`acp_engines`). The block covers pushes, pull requests and `gh`
writes; commits are allowed (D123), and the user's login stays, so fetch, pull and `gh`
reads work.
"""

from claude_agent_sdk.types import HookCallback, HookContext, HookInput, HookJSONOutput

from nestd.providers.git_commands import is_git_write
from nestd.providers.git_tools import DENY_REASON, tool_writes

__all__ = [
    "DENY_REASON",
    "GIT_WORKTREE_RULES",
    "GIT_WRITE_RULES",
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
AUTOPILOT_DENY_REASON = (
    "Nest: Autopilot leaves pushes, pull requests and removing worktrees to the user"
)
WORKTREE_DENY_REASON = "Nest: Autopilot leaves removing worktrees to the user"


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
