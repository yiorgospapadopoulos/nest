"""Grok Build under Nest's git guard (B153): Grok runs a call unasked where the user's
rules allow it, so Nest's answer to its hook is what stops a push, and a guarded run's
plugin refuses the same even when Nest cannot answer.
"""

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import JsonValue

from nestd.providers.acp_engines import GROK
from nestd.providers.acp_grok import HOOK_ID, hook_answer
from nestd.providers.acp_permissions import AcpRules
from nestd.providers.git_guard import DENY_REASON, WORKTREE_DENY_REASON
from nestd.providers.push_block import GROK_HOOK, helpers
from nestd.providers.push_check import main
from tests.test_acp_provider import FakeAgent, load, open_run

SESSION = "01a1bdf2"


def shell(command: str, **fields: JsonValue) -> dict[str, JsonValue]:
    """A hook call as Grok sends one for its shell tool."""
    return {
        "hookCallbackId": HOOK_ID,
        "hookEventName": "pre_tool_use",
        "sessionId": SESSION,
        "toolName": "run_terminal_command",
        "toolInput": {"command": command, "description": "push"},
        "toolInputTruncated": False,
        **fields,
    }


def mcp(tool: str, args: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "sessionId": SESSION,
        "toolName": tool,
        "toolInput": {"tool_name": tool, "tool_input": args},
    }


GUARDED = AcpRules("bypassPermissions", True, (Path("/repo"),), nest={"nest": frozenset({"x"})})
NORMAL = AcpRules("bypassPermissions", False, (Path("/repo"),), subagents=True)


@pytest.mark.parametrize("command", ["git push origin main", "cd x && gh pr create --fill"])
def test_a_guarded_runs_push_is_denied(command: str) -> None:
    assert hook_answer(shell(command), GUARDED, SESSION) == {
        "decision": "deny",
        "reason": DENY_REASON,
    }


def test_everything_else_goes_on_to_grok_asking() -> None:
    assert hook_answer(shell("git commit -m x"), GUARDED, SESSION) == {}


def test_a_command_grok_cut_short_is_denied_in_a_guarded_run() -> None:
    answer = hook_answer(shell("echo", toolInputTruncated=True), GUARDED, SESSION)

    assert answer == {"decision": "deny", "reason": DENY_REASON}


def test_a_normal_chats_own_agent_may_push_but_not_its_subagents() -> None:
    own = hook_answer(shell("git push"), NORMAL, SESSION)
    typed = hook_answer(shell("git push", subagentType="general-purpose"), NORMAL, SESSION)
    child = hook_answer(shell("git push", sessionId="child"), NORMAL, SESSION)

    assert own == {}
    assert typed == child == {"decision": "deny", "reason": DENY_REASON}


def test_an_mcp_tool_that_opens_a_pull_request_is_denied_but_nests_own_is_not() -> None:
    github = hook_answer(mcp("github__create_pull_request", {"title": "x"}), GUARDED, SESSION)
    terminal = hook_answer(mcp("term__run", {"command": "git push"}), GUARDED, SESSION)
    own = hook_answer(mcp("nest__x", {}), GUARDED, SESSION)

    assert github == terminal == {"decision": "deny", "reason": DENY_REASON}
    assert own == {}


def test_autopilot_may_push_but_not_remove_a_worktree() -> None:
    rules = AcpRules("bypassPermissions", False, (Path("/repo"),), worktrees=True)

    assert hook_answer(shell("git push"), rules, SESSION) == {}
    assert hook_answer(shell("git worktree remove ../wt"), rules, SESSION) == {
        "decision": "deny",
        "reason": WORKTREE_DENY_REASON,
    }


@pytest.mark.parametrize("guarded", [True, False])
async def test_every_session_asks_nests_hook_and_a_guarded_one_loads_the_plugin(
    tmp_path: Path, guarded: bool
) -> None:
    agent = FakeAgent(load("opencode-text", tmp_path))
    run, _, _ = await open_run(agent, tmp_path, engine=GROK, guard_git=guarded)

    [opened] = agent.requests("session/new")
    meta = cast("dict[str, Any]", opened["_meta"])
    assert (meta["yoloMode"], meta["autoMode"]) == (False, False)
    [hook] = meta["x.ai/hooks"]["PreToolUse"]
    assert hook["hookCallbackIds"] == [HOOK_ID]
    assert ("pluginDirs" in meta) is guarded
    if guarded:
        [plugin] = meta["pluginDirs"]
        command = plugin_command(Path(plugin))
        assert command["failClosed"] is True
        assert is_file(Path(command["command"]))
    await run.close()


def is_file(path: Path) -> bool:
    return path.is_file()


def plugin_command(plugin: Path) -> dict[str, Any]:
    hooks = json.loads((plugin / "hooks" / "hooks.json").read_text())
    [entry] = hooks["hooks"]["PreToolUse"]
    [command] = entry["hooks"]
    return cast("dict[str, Any]", command)


@pytest.mark.parametrize(
    ("event", "code"),
    [
        ({"tool_name": "run_terminal_command", "tool_input": {"command": "git push"}}, 2),
        ({"tool_name": "run_terminal_command", "tool_input": {"command": "ls"}}, 0),
        ({"tool_name": "run_terminal_command", "tool_input": {}}, 2),
        ("not an event", 2),
    ],
)
def test_the_plugins_check_refuses_pushes_and_what_it_cannot_read(event: object, code: int) -> None:
    stderr = io.StringIO()

    found = main(["grok-hook"], io.StringIO(json.dumps(event)), io.StringIO(), stderr)

    assert found == code
    assert (DENY_REASON in stderr.getvalue()) is (code == 2)


def test_the_plugins_script_runs_the_check() -> None:
    event = {"tool_name": "run_terminal_command", "tool_input": {"command": "git push"}}
    found = subprocess.run(  # noqa: S603
        [str(helpers() / GROK_HOOK)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={"PATH": str(Path(sys.executable).parent)},
    )

    assert found.returncode == 2
    assert DENY_REASON in found.stderr
