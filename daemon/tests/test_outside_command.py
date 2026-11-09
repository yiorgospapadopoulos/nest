"""B151: the `nest` command and `nest mcp` work Nest's chats through the outside API."""

import argparse
import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.outside.client import InsideNestError, NestClient
from nestd.outside.command import add_commands, execute
from nestd.outside.mcp_server import Tools, tools_for
from nestd.outside.models import ClientKind
from nestd.providers.base import AgentTool, ToolRefusedError
from tests.api_client import Api, running_api
from tests.fake_provider import FakeRun, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.tool_support import tool_text


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.ctx.repos.register(init_repo(tmp_path / "repo"))
        yield running


async def client(api: Api, kind: ClientKind, access: str) -> NestClient:
    switched = await api.http.put(f"/api/outside-clients/{kind}", json={"access": access})
    assert switched.status_code == 200, switched.text

    async def token(asked: ClientKind) -> str:
        issued = await api.ctx.outside.issue_token(asked)
        assert issued is not None
        return issued

    return NestClient(kind, api.ctx.paths, transport=api.transport, token_source=token)


async def nest(nest_client: NestClient, *argv: str) -> int:
    parser = argparse.ArgumentParser(prog="nest")
    add_commands(parser.add_subparsers(dest="command", required=True).add_parser)
    return await execute(parser.parse_args(argv), nest_client)


def tool(tools: tuple[AgentTool, ...], name: str) -> AgentTool:
    return next(t for t in tools if t.name == name)


async def test_nest_new_waits_for_the_chats_answer(
    api: Api, capsys: pytest.CaptureFixture[str]
) -> None:
    api.provider.script(reply("Fixed the bug."))
    shell = await client(api, "shell", "full")

    code = await nest(shell, "new", "Fix the bug", "--project", "repo", "--wait", "--json")

    assert code == 0
    chat = json.loads(capsys.readouterr().out)
    assert (chat["state"], chat["last_answer"]) == ("idle", "Fixed the bug.")
    assert chat["started_by"] == "nest command"
    assert chat["permission_mode"] == "default"


async def test_a_wait_that_runs_out_says_the_chat_still_works(
    api: Api, capsys: pytest.CaptureFixture[str]
) -> None:
    gate = asyncio.Event()

    async def works_on(_run: FakeRun) -> None:
        await gate.wait()

    api.provider.script(works_on)
    shell = await client(api, "shell", "full")

    code = await nest(shell, "new", "Go", "--project", "repo", "--wait", "--timeout", "0.02")

    assert code == 3
    assert "Status: running" in capsys.readouterr().out
    gate.set()


async def test_a_chat_is_named_by_the_start_of_its_id(
    api: Api, capsys: pytest.CaptureFixture[str]
) -> None:
    api.provider.script(reply("Hello."))
    shell = await client(api, "shell", "full")
    await nest(shell, "new", "Say hello", "--project", "repo", "--wait", "--json")
    chat_id = json.loads(capsys.readouterr().out)["id"]

    assert await nest(shell, "show", chat_id[:8]) == 0
    assert "Hello." in capsys.readouterr().out


async def test_a_token_nest_dropped_is_asked_for_again(api: Api) -> None:
    shell = await client(api, "shell", "read")
    await shell.status()

    # Switching it off and on drops its token, as a restart of the daemon does.
    await api.http.delete("/api/outside-clients/shell")
    await api.http.put("/api/outside-clients/shell", json={"access": "read"})

    assert (await shell.status()).access == "read"


async def test_nest_mcp_offers_no_tools_inside_nests_own_chats(api: Api) -> None:
    async def inside(_kind: ClientKind) -> str:
        raise InsideNestError("inside")

    nest_client = NestClient(
        "claude_code", api.ctx.paths, transport=api.transport, token_source=inside
    )

    assert await tools_for(nest_client) == ()


async def test_a_tool_above_the_clients_level_says_how_to_raise_it(api: Api) -> None:
    other = await client(api, "other", "read")
    tools = Tools(other).all()

    with pytest.raises(ToolRefusedError, match="Settings > Terminal agents"):
        await tool(tools, "start_chat").handler({"project": "repo", "prompt": "Go"})
    assert "No chats." in await tool_text(tool(tools, "list_chats"), {})
