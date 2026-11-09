"""Cursor's agent under Nest's git guard (B153): its requests carry no input, so Nest reads
commands from their titles and MCP arguments from their content, and its settings are a
copy of the user's that asks before everything.
"""

import json
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.config.models import PermissionMode
from nestd.engine.cursor_config import CONFIG_FILE, write_config
from nestd.providers.acp import AcpNotReadyError
from nestd.providers.acp_engines import CURSOR
from nestd.providers.acp_events import AcpStream, NestTools, ToolCall
from nestd.providers.acp_permissions import AcpPermissions, AcpRules
from nestd.providers.git_tools import DENY_REASON
from tests.recording_sink import RecordingSink
from tests.test_acp_permissions import Handler
from tests.test_acp_provider import FakeAgent, load, open_run

NEST: NestTools = {"nest": frozenset({"artifact_list"})}


async def verdict(
    tmp_path: Path,
    fields: dict[str, JsonValue],
    mode: PermissionMode = "bypassPermissions",
    guarded: bool = True,
) -> tuple[str, ToolCall, Handler]:
    handler = Handler()
    rules = AcpRules(mode, guarded=guarded, folders=(tmp_path,), nest=NEST)
    permissions = AcpPermissions(handler, lambda: rules, AcpStream(RecordingSink(), NEST))
    call = ToolCall("call-1")
    call.update(fields)
    return await permissions.verdict(call), call, handler


def mcp_request(title: str, args: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """A permission request as Cursor sends one for an MCP tool."""
    shown = f"```json\n{json.dumps(args, indent=2)}\n```"
    return {
        "kind": "other",
        "title": title,
        "content": [{"type": "content", "content": {"type": "text", "text": shown}}],
    }


@pytest.mark.parametrize(
    "title",
    [
        "`git push origin main`",
        "`git -C repo push`",
        "`echo \\`date\\` && gh pr create --fill`",
    ],
)
async def test_a_guarded_runs_push_in_a_title_only_request_is_rejected(
    tmp_path: Path, title: str
) -> None:
    found, call, handler = await verdict(tmp_path, {"kind": "execute", "title": title})

    assert found == "reject"
    assert call.refused == DENY_REASON
    assert handler.requests == []


async def test_a_command_is_asked_without_its_backticks(tmp_path: Path) -> None:
    title = "`echo \\`date\\``"

    found, _call, handler = await verdict(
        tmp_path, {"kind": "execute", "title": title}, mode="default", guarded=False
    )

    assert found == "reject"
    [asked] = handler.requests
    assert asked.tool_input == {"command": "echo `date`"}


@pytest.mark.parametrize(
    ("title", "args"),
    [
        ("github: create_pull_request", {"title": "x", "head": "b"}),
        ("terminal: run", {"command": "git push origin main"}),
        ("terminal: run", {}),
    ],
)
async def test_a_guarded_runs_risky_mcp_tool_is_rejected_from_its_shown_arguments(
    tmp_path: Path, title: str, args: dict[str, JsonValue]
) -> None:
    found, _call, handler = await verdict(tmp_path, mcp_request(title, args))

    assert found == "reject"
    assert handler.requests == []


async def test_the_users_mcp_tool_is_asked_with_its_server_and_arguments(tmp_path: Path) -> None:
    found, _call, handler = await verdict(
        tmp_path, mcp_request("notes: search", {"query": "x"}), mode="default"
    )

    assert found == "reject"
    [asked] = handler.requests
    assert (asked.tool_name, asked.tool_input) == ("mcp__notes__search", {"query": "x"})


async def test_the_tool_calls_own_input_names_the_server(tmp_path: Path) -> None:
    raw: dict[str, JsonValue] = {
        "providerIdentifier": "terminal",
        "toolName": "run",
        "args": {"command": "git push"},
    }

    found, _call, handler = await verdict(
        tmp_path, {"kind": "other", "title": "terminal: run", "rawInput": raw}
    )

    assert found == "reject"
    assert handler.requests == []


async def test_nests_own_tool_passes_without_asking(tmp_path: Path) -> None:
    found, _call, handler = await verdict(
        tmp_path, mcp_request("nest: artifact_list", {"kind": "page"}), mode="default"
    )

    assert found == "allow"
    assert handler.requests == []


async def test_a_nest_tool_title_carrying_a_command_is_judged(tmp_path: Path) -> None:
    found, _call, _handler = await verdict(
        tmp_path, mcp_request("nest: artifact_list", {"command": "git push"})
    )

    assert found == "reject"


def test_the_users_settings_stay_but_everything_is_asked(tmp_path: Path) -> None:
    user = tmp_path / "user"
    user.mkdir()
    (user / CONFIG_FILE).write_text(
        json.dumps(
            {
                "model": {"modelId": "fast"},
                "attribution": {"attributeCommitsToAgent": False},
                "approvalMode": "unrestricted",
                "permissions": {"allow": ["Shell(*)"], "deny": []},
                "webFetchDomainAllowlist": ["*"],
                "autoAcceptWebSearch": True,
            }
        )
    )
    ours = tmp_path / "nest"
    ours.mkdir()
    (ours / "permissions.json").write_text('{"allow": ["Shell(*)"]}')

    write_config(ours, user)

    written = json.loads((ours / CONFIG_FILE).read_text())
    assert written == {
        "model": {"modelId": "fast"},
        "attribution": {"attributeCommitsToAgent": False},
        "approvalMode": "allowlist",
        "permissions": {"allow": [], "deny": []},
        "autoAcceptWebSearch": False,
    }
    assert not (ours / "permissions.json").exists()


def test_without_the_users_settings_nest_writes_only_its_own(tmp_path: Path) -> None:
    user = tmp_path / "user"
    user.mkdir()
    (user / CONFIG_FILE).write_text("not json")

    write_config(tmp_path / "nest", user)

    written = json.loads((tmp_path / "nest" / CONFIG_FILE).read_text())
    assert written["approvalMode"] == "allowlist"
    assert written["permissions"] == {"allow": [], "deny": []}


async def test_a_run_kept_to_a_write_root_is_refused(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-text", tmp_path))

    with pytest.raises(AcpNotReadyError, match="Cursor agent cannot keep"):
        await open_run(agent, tmp_path, engine=CURSOR, write_root=tmp_path / "own")
