"""B151: outside clients reach Nest's chats at the level the user gave each, and nothing
else; their chats cannot push; Nest's own agents get no token."""

import asyncio
import json
import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest

from nestd.events import types
from nestd.gitops.runner import CommandError
from nestd.outside.config import CHECKOUT_PROGRAM, nest_program
from nestd.outside.models import ClientKind
from nestd.outside.socket import ClientSocket, IssueToken, runs_under
from nestd.pixies.models import CreatePixie
from nestd.sessions.models import IN_FLIGHT, CreateSession
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo

MCP_ADD = ("mcp", "add", "--scope", "user", "nest-app", "--")
MCP_REMOVE = ("mcp", "remove", "--scope", "user", "nest-app")


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.ctx.repos.register(init_repo(tmp_path / "repo"))
        yield running


async def turn_on(api: Api, kind: ClientKind, access: str) -> str:
    """Switches the client on through Settings and returns a token it would get."""
    response = await api.http.put(f"/api/outside-clients/{kind}", json={"access": access})
    assert response.status_code == 200, response.text
    token = await api.ctx.outside.issue_token(kind)
    assert token is not None
    return token


def as_client(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def a_chat(api: Api) -> str:
    session = await api.ctx.sessions.create(CreateSession(repo="repo", prompt="Hi"))
    await until(lambda: bool(api.provider.runs))
    return session.id


async def settled(api: Api, session_id: str) -> bool:
    return (await api.ctx.sessions.get(session_id)).state not in IN_FLIGHT


async def test_a_client_token_reaches_only_the_outside_api(api: Api) -> None:
    token = await turn_on(api, "shell", "full")
    device = api.http.headers["Authorization"]

    assert (await api.http.get("/api/sessions", headers=as_client(token))).status_code == 401
    assert (await api.http.get("/api/outside-clients", headers=as_client(token))).status_code == 401
    outside = await api.http.get("/api/outside/status", headers={"Authorization": device})
    assert outside.status_code == 401
    assert (await api.http.get("/api/outside/status", headers=as_client(token))).json()[
        "access"
    ] == "full"


async def test_each_level_allows_only_its_actions(api: Api) -> None:
    chat = await a_chat(api)
    token = await turn_on(api, "shell", "read")
    start = {"project": "repo", "prompt": "Fix it"}

    listed = await api.http.get("/api/outside/chats", headers=as_client(token))
    assert [c["id"] for c in listed.json()] == [chat]
    refused = await api.http.post(
        f"/api/outside/chats/{chat}/messages", json={"text": "More"}, headers=as_client(token)
    )
    assert (refused.status_code, refused.json()["needs"]) == (403, "message")
    assert "Settings > Terminal agents" in refused.json()["detail"]

    await turn_on(api, "shell", "message")
    sent = await api.http.post(
        f"/api/outside/chats/{chat}/messages", json={"text": "More"}, headers=as_client(token)
    )
    assert sent.status_code == 200, sent.text
    refused = await api.http.post("/api/outside/chats", json=start, headers=as_client(token))
    assert (refused.status_code, refused.json()["needs"]) == (403, "full")

    await turn_on(api, "shell", "full")
    started = await api.http.post("/api/outside/chats", json=start, headers=as_client(token))
    assert started.status_code == 201, started.text
    assert started.json()["started_by"] == "nest command"


async def test_a_chat_a_client_starts_cannot_push_and_says_where_it_came_from(api: Api) -> None:
    token = await turn_on(api, "other", "full")

    started = await api.http.post(
        "/api/outside/chats",
        json={"project": "repo", "prompt": "Fix it", "worktree": True},
        headers=as_client(token),
    )

    assert started.status_code == 201, started.text
    session = await api.ctx.sessions.get(started.json()["id"])
    assert session.started_by_client == "other"
    assert session.mode == "worktree"
    assert not session.movable
    await until(lambda: bool(api.provider.runs))
    assert api.provider.runs[-1].spec.guard_git is True
    events = await api.ctx.bus.session_events(session.id)
    first = next(e for e in events if e.type == types.SESSION_USER_MESSAGE)
    assert first.payload["from_client"] == "other"


async def test_a_client_may_not_start_a_chat_in_a_looser_mode(api: Api) -> None:
    token = await turn_on(api, "shell", "full")

    refused = await api.http.post(
        "/api/outside/chats",
        json={"project": "repo", "prompt": "Go", "permission_mode": "bypassPermissions"},
        headers=as_client(token),
    )

    assert refused.status_code == 422


async def test_a_client_starts_at_most_five_chats_a_day(api: Api) -> None:
    token = await turn_on(api, "shell", "full")
    for _ in range(5):
        chat = await api.ctx.sessions.create(CreateSession(repo="repo", prompt="Earlier"))
        await until(lambda chat_id=chat.id: settled(api, chat_id))
        await api.ctx.db.execute(
            "UPDATE sessions SET started_by_client = 'shell' WHERE id = ?", (chat.id,)
        )

    refused = await api.http.post(
        "/api/outside/chats", json={"project": "repo", "prompt": "Go"}, headers=as_client(token)
    )

    assert refused.status_code == 403
    assert "today" in refused.json()["detail"]


async def test_a_client_starts_at_most_two_chats_running(api: Api) -> None:
    token = await turn_on(api, "shell", "full")
    for _ in range(2):
        chat = await api.ctx.sessions.create(CreateSession(repo="repo", prompt="Earlier"))
        await until(lambda chat_id=chat.id: settled(api, chat_id))
        await api.ctx.db.execute(
            "UPDATE sessions SET started_by_client = 'shell', state = 'running' WHERE id = ?",
            (chat.id,),
        )

    refused = await api.http.post(
        "/api/outside/chats", json={"project": "repo", "prompt": "Go"}, headers=as_client(token)
    )

    assert refused.status_code == 403
    assert "running" in refused.json()["detail"]


async def test_a_message_that_calls_a_pixie_needs_full_access(api: Api) -> None:
    chat = await a_chat(api)
    await api.ctx.pixies.create(CreatePixie(name="Closer"))
    await api.ctx.pixies.create(CreatePixie(name="Auditor", hidden=True))
    token = await turn_on(api, "shell", "message")

    async def message(text: str) -> httpx.Response:
        return await api.http.post(
            f"/api/outside/chats/{chat}/messages", json={"text": text}, headers=as_client(token)
        )

    refused = await message("@closer merge it")
    assert (refused.status_code, refused.json()["needs"]) == (403, "full")
    await turn_on(api, "shell", "full")
    hidden = await message("@auditor look")
    assert hidden.status_code == 403
    assert "hidden" in hidden.json()["detail"]
    assert (await message("ask an email@closer.dev friend")).status_code == 200


async def test_pixie_chats_are_never_touched(api: Api) -> None:
    chat = await a_chat(api)
    pixie = await api.ctx.pixies.create(CreatePixie(name="Helper"))
    await api.ctx.db.execute("UPDATE sessions SET pixie_id = ? WHERE id = ?", (pixie.id, chat))
    token = await turn_on(api, "shell", "full")

    assert (
        await api.http.get(f"/api/outside/chats/{chat}", headers=as_client(token))
    ).status_code == 403
    sent = await api.http.post(
        f"/api/outside/chats/{chat}/messages", json={"text": "Hi"}, headers=as_client(token)
    )
    assert sent.status_code == 403
    transcript = await api.http.get(
        f"/api/outside/chats/{chat}/transcript", headers=as_client(token)
    )
    assert transcript.status_code == 403


async def test_switching_a_client_off_stops_its_tokens_at_once(api: Api) -> None:
    token = await turn_on(api, "other", "read")
    assert (await api.http.get("/api/outside/status", headers=as_client(token))).status_code == 200

    off = await api.http.delete("/api/outside-clients/other")

    assert off.json()["on"] is False
    assert (await api.http.get("/api/outside/status", headers=as_client(token))).status_code == 401
    assert await api.ctx.outside.issue_token("other") is None


async def test_claude_code_gets_nest_in_its_own_config_only_while_on(api: Api) -> None:
    api.claude.script(
        *MCP_REMOVE, reply=CommandError(["claude"], 1, 'No MCP server named "nest-app"')
    )
    command = api.ctx.outside.config.command("claude_code")
    assert command is not None
    api.claude.script(*MCP_ADD, *command, reply="")

    on = await api.http.put("/api/outside-clients/claude_code", json={"access": "message"})

    assert on.status_code == 200, on.text
    assert on.json()["command"][1:] == ["mcp", "--client", "claude_code"]
    added = [args for _, args in api.claude.runs() if args[:2] == ("mcp", "add")]
    assert added == [(*MCP_ADD, *command)]

    api.claude.script(*MCP_REMOVE, reply="")
    await api.http.delete("/api/outside-clients/claude_code")
    assert [args for _, args in api.claude.runs()][-1] == MCP_REMOVE


async def test_a_client_whose_config_cannot_be_written_stays_off(api: Api) -> None:
    api.claude.script(*MCP_REMOVE, reply="")
    # Claude Code is not set up to answer `mcp add`, so it fails.

    failed = await api.http.put("/api/outside-clients/claude_code", json={"access": "full"})

    assert failed.status_code == 502
    clients = (await api.http.get("/api/outside-clients")).json()
    assert next(c for c in clients if c["kind"] == "claude_code")["on"] is False
    assert await api.ctx.outside.issue_token("claude_code") is None


def test_the_nest_command_is_found_where_it_outlives_updates(tmp_path: Path) -> None:
    installed = tmp_path / ".local" / "bin" / "nest"
    installed.parent.mkdir(parents=True)
    installed.write_text("")

    assert nest_program(tmp_path) == installed
    # Without the installer's link, a checkout's own (this one's, in its .venv).
    assert nest_program(tmp_path / "elsewhere") == CHECKOUT_PROGRAM


# The socket


@pytest.fixture
def folder() -> Iterator[Path]:
    """A short folder: Unix socket paths are limited to about 104 bytes."""
    root = Path(tempfile.mkdtemp(prefix="nx-", dir="/tmp"))
    yield root / "data"
    shutil.rmtree(root)


async def ask(path: Path, line: bytes) -> dict[str, str]:
    reader, writer = await asyncio.open_unix_connection(path)
    writer.write(line)
    data = await reader.read()
    writer.close()
    await writer.wait_closed()
    answer: dict[str, str] = json.loads(data)
    return answer


def on_only(kind: str) -> IssueToken:
    async def issue(asked: ClientKind) -> str | None:
        return f"token-{asked}" if asked == kind else None

    return issue


async def serve(
    folder: Path, parents: dict[int, int], daemon: int = 500, sessions: dict[int, int] | None = None
) -> ClientSocket:
    async def read_parents() -> dict[int, int]:
        return parents

    server = ClientSocket(
        folder / "outside.sock",
        on_only("shell"),
        daemon_pid=daemon,
        peer_pid=lambda _: 900,
        parents=read_parents,
        session=lambda pid: (sessions or {}).get(pid, pid),
    )
    await server.start()
    return server


async def test_the_socket_gives_a_token_to_a_client_that_is_on(folder: Path) -> None:
    server = await serve(folder, {900: 80, 80: 1})
    try:
        assert await ask(folder / "outside.sock", b"shell\n") == {"token": "token-shell"}
        assert await ask(folder / "outside.sock", b"codex\n") == {"error": "off"}
        assert await ask(folder / "outside.sock", b"nobody\n") == {"error": "unknown_client"}
    finally:
        await server.stop()


async def test_nothing_running_under_the_daemon_gets_a_token(folder: Path) -> None:
    # The asker is a shell of an agent the daemon started: 900 -> 700 -> 500 (the daemon).
    server = await serve(folder, {900: 700, 700: 500, 500: 1})
    try:
        assert await ask(folder / "outside.sock", b"shell\n") == {"error": "inside_nest"}
    finally:
        await server.stop()


async def test_a_detached_process_gets_no_token(folder: Path) -> None:
    # Left to launchd, as a double fork leaves it.
    server = await serve(folder, {900: 1})
    try:
        assert await ask(folder / "outside.sock", b"shell\n") == {"error": "inside_nest"}
    finally:
        await server.stop()


async def test_a_process_in_an_agents_session_gets_no_token(folder: Path) -> None:
    # Its parent shell is gone, but its session began with an agent's command (700).
    server = await serve(folder, {900: 650, 650: 1, 700: 500, 500: 1}, sessions={900: 700})
    try:
        assert await ask(folder / "outside.sock", b"shell\n") == {"error": "inside_nest"}
    finally:
        await server.stop()


async def test_a_process_whose_session_leader_is_gone_gets_no_token(folder: Path) -> None:
    server = await serve(folder, {900: 650, 650: 80, 80: 1}, sessions={900: 777})
    try:
        assert await ask(folder / "outside.sock", b"shell\n") == {"error": "inside_nest"}
    finally:
        await server.stop()


def test_a_parent_loop_ends_the_walk() -> None:
    assert not runs_under(900, 500, {900: 800, 800: 900})
    assert runs_under(os.getpid(), os.getppid(), {os.getpid(): os.getppid()})
