"""Grok Build's git guard (B153).

Grok skips its permission requests where the user's own rules or grants allow a call (its
config, a project's, and Claude Code's settings files), so a request cannot be what stops
a push. What it never skips is the client's own PreToolUse hook (`x.ai/hooks` in a
session's `_meta`): before every tool call, its subagents' included, it asks Nest
`_x.ai/hooks/run`, and a deny stops the call while the turn goes on (checked in 1.0.79).
Nest answers it at once: a shell command that pushes, writes a pull request or (on
Autopilot) removes a worktree, or an MCP tool that does, is denied where the run blocks
it; everything else goes on to Grok's usual permission request, which Nest judges as any
engine's.

The client hook fails open when Nest does not answer (a lost connection), so a guarded
run also loads Nest's plugin, whose command hook fails closed and refuses the same shell
commands (`push_check grok-hook`). Its events do not say which agent runs them, so a
normal chat's subagents have the client hook only.
"""

import json
from pathlib import Path

from pydantic import JsonValue

from nestd.providers.acp_permissions import AcpRules
from nestd.providers.acp_rpc import JsonObject
from nestd.providers.codex_items import obj, text
from nestd.providers.git_guard import DENY_REASON, WORKTREE_DENY_REASON, is_git_write, tool_writes
from nestd.providers.push_block import GROK_HOOK, helper_files, helpers

HOOK_METHOD = "_x.ai/hooks/run"
HOOK_ID = "nest-guard"
# Grok's longest wait for a client hook.
HOOK_TIMEOUT_SECONDS = 600
SHELL_TOOL = "run_terminal_command"
_PLUGIN = "grok-guard"
_ALLOW: JsonObject = {}


def hook_meta() -> JsonObject:
    """What a session's `_meta` carries so Grok asks Nest's hook first, and never runs on
    its own (`yoloMode`, `autoMode`).
    """
    hook: JsonValue = {"hookCallbackIds": [HOOK_ID], "timeoutS": HOOK_TIMEOUT_SECONDS}
    return {"yoloMode": False, "autoMode": False, "x.ai/hooks": {"PreToolUse": [hook]}}


def hook_answer(params: JsonObject, rules: AcpRules, session_id: str | None) -> JsonValue:
    """Nest's answer to `_x.ai/hooks/run`: a deny for a call the run blocks, else nothing,
    which leaves the call to Grok's permission request.
    """
    subagent = bool(text(params.get("subagentType"))) or (
        session_id is not None and text(params.get("sessionId")) not in ("", session_id)
    )
    pushes = rules.guarded or (rules.subagents and subagent)
    if not pushes and not rules.worktrees:
        return _ALLOW
    tool, tool_input = text(params.get("toolName")), obj(params.get("toolInput"))
    if tool == SHELL_TOOL:
        command = text(tool_input.get("command"))
        truncated = params.get("toolInputTruncated") is True
        if (pushes and truncated) or is_git_write(
            command, pushes=pushes, worktrees=rules.worktrees
        ):
            return _deny(pushes)
        return _ALLOW
    server, _, name = tool.partition("__")
    if name and server not in rules.nest:
        inner = obj(tool_input.get("tool_input"))
        if tool_writes(f"mcp__{server}__{name}", inner, pushes=pushes, worktrees=rules.worktrees):
            return _deny(pushes)
    return _ALLOW


def plugin_dir() -> Path:
    """Nest's plugin folder for a guarded run: a command hook on Grok's shell tool that
    refuses what pushes, and refuses the call when it cannot run.
    """
    script = helpers() / GROK_HOOK
    hooks = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": SHELL_TOOL,
                    "hooks": [
                        {
                            "type": "command",
                            "command": str(script),
                            "timeout": 10,
                            "failClosed": True,
                        }
                    ],
                }
            ]
        }
    }
    folder = helper_files(lambda _folder: {f"{_PLUGIN}/hooks/hooks.json": json.dumps(hooks)})
    return folder / _PLUGIN


def _deny(pushes: bool) -> JsonObject:
    return {"decision": "deny", "reason": DENY_REASON if pushes else WORKTREE_DENY_REASON}
