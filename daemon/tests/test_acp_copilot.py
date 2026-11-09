"""Copilot CLI under Nest's git guard (B153): its own denials for a guarded run's pushes,
which beat the user's saved approvals, a subagent's push refused from the mark on its
tool call, and Nest's own tools known by the name its first tool call gives.
"""

from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.providers.acp_engines import COPILOT
from nestd.providers.acp_events import AcpStream, NestTools, ToolCall
from nestd.providers.acp_permissions import AcpPermissions, AcpRules
from nestd.providers.git_tools import DENY_REASON
from tests.recording_sink import RecordingSink
from tests.test_acp_permissions import Handler
from tests.test_acp_provider import FakeAgent, load, open_run

NEST: NestTools = {"nest": frozenset({"artifact_list"})}
SUBAGENT: dict[str, JsonValue] = {"github.com/copilot": {"agentId": "af460652"}}


def denials(args: tuple[str, ...]) -> set[str]:
    return {arg.removeprefix("--deny-tool=") for arg in args if arg.startswith("--deny-tool=")}


@pytest.mark.parametrize(("pushes", "worktrees"), [(True, False), (False, False), (False, True)])
async def test_a_runs_denials_follow_what_it_may_not_do(
    tmp_path: Path, pushes: bool, worktrees: bool
) -> None:
    agent = FakeAgent(load("opencode-text", tmp_path))
    run, _, _ = await open_run(
        agent, tmp_path, engine=COPILOT, guard_git=pushes, guard_worktrees=worktrees
    )

    denied = denials(agent.transport.launch.args)

    assert ("shell(git push)" in denied) is pushes
    assert ("shell(gh pr)" in denied) is pushes
    assert ("shell(git worktree remove:*)" in denied) is worktrees
    await run.close()


def test_the_users_allow_all_is_switched_off() -> None:
    assert COPILOT.env["COPILOT_ALLOW_ALL"] == "false"


async def judged(
    updates: list[Mapping[str, JsonValue]], rules: AcpRules
) -> tuple[str, ToolCall, Handler]:
    """Each update of one call in turn, as the tool call and then the request bring them."""
    handler = Handler()
    permissions = AcpPermissions(handler, lambda: rules, AcpStream(RecordingSink(), NEST))
    call = ToolCall("call_ffc3df2c")
    for fields in updates:
        call.update(dict(fields))
    return await permissions.verdict(call), call, handler


PUSH: dict[str, JsonValue] = {
    "kind": "execute",
    "title": "git push origin main",
    "rawInput": {"command": "git push origin main", "commands": ["git push"]},
}


async def test_a_normal_chats_subagent_may_not_push(tmp_path: Path) -> None:
    rules = AcpRules("bypassPermissions", False, (tmp_path,), subagents=True)
    marked: dict[str, JsonValue] = {"kind": "execute", "title": "run it", "_meta": SUBAGENT}

    found, call, handler = await judged([marked, PUSH], rules)

    assert found == "reject"
    assert call.refused == DENY_REASON
    assert handler.requests == []


async def test_the_chats_own_agent_may_still_push(tmp_path: Path) -> None:
    rules = AcpRules("bypassPermissions", False, (tmp_path,), subagents=True)

    found, _, _ = await judged([{"kind": "execute", "title": "push"}, PUSH], rules)

    assert found == "allow"


async def test_nests_own_tool_asked_by_its_bare_name_passes(tmp_path: Path) -> None:
    rules = AcpRules("default", True, (tmp_path,), nest=NEST)
    named: dict[str, JsonValue] = {"kind": "other", "title": "nest-artifact_list"}
    asked: dict[str, JsonValue] = {"kind": "other", "title": "artifact_list", "rawInput": {}}

    found, _, handler = await judged([named, asked], rules)

    assert found == "allow"
    assert handler.requests == []


async def test_a_bare_name_without_nests_server_is_asked(tmp_path: Path) -> None:
    rules = AcpRules("default", True, (tmp_path,), nest=NEST)
    other: dict[str, JsonValue] = {"kind": "other", "title": "notes-artifact_list"}
    asked: dict[str, JsonValue] = {"kind": "other", "title": "artifact_list", "rawInput": {}}

    found, _, handler = await judged([other, asked], rules)

    assert found == "reject"
    assert len(handler.requests) == 1
