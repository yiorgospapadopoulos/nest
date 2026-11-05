"""A pixie called with call_pixie removes the worktree of the chat that called it (B127).

The caller is on Codex so the pixie runs as a session of its own, on the scripted provider,
where the test can call its tools.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.providers.base import AgentTool, ToolRefusedError
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.codex_support import note, turn_completed
from tests.fake_provider import FakeRun, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import git, init_repo
from tests.test_api_sessions import create
from tests.test_pixie_parity import Called, Caller, Scene, soon

TOOL = "worktree"


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


@pytest.fixture
async def scene(api: Api) -> Scene:
    scene = Scene(api, Called(api, "claude"), Caller(api, "codex"))
    await scene.pixie()
    return scene


class Pixie:
    """A called pixie's turn: it asks for `args`, then works until the test says `finish`."""

    def __init__(self, api: Api, args: dict[str, JsonValue] | None) -> None:
        self.recorded = asyncio.Event()
        self.go = asyncio.Event()
        self.run: FakeRun | None = None
        self.refusal: str | None = None
        self._args = args
        api.provider.script(self._play)

    async def _play(self, run: FakeRun) -> None:
        self.run = run
        await run.sink.provider_session_id("sdk-called")
        if self._args is not None:
            try:
                await tool_of(run).handler(self._args)
            except ToolRefusedError as error:
                self.refusal = str(error)
        self.recorded.set()
        await self.go.wait()
        await reply("Done.", provider_session_id="sdk-called")(run)


def tool_of(run: FakeRun) -> AgentTool:
    return next(tool for tool in run.spec.nest_tools if tool.name == TOOL)


def tools_of(run: FakeRun) -> list[str]:
    return [tool.name for tool in run.spec.nest_tools if tool.name == TOOL]


async def opened(scene: Scene) -> Path:
    """The caller's worktree, its first turn running."""
    await scene.caller.open(mode="worktree")
    path = (await scene.detail())["worktree_path"]
    assert path is not None
    return Path(path)


async def reached(api: Api, chat_id: str, state: str = "idle") -> None:
    async def there() -> bool:
        return (await api.http.get(f"/api/sessions/{chat_id}")).json()["state"] == state

    await until(there)


async def settled(api: Api, chat_id: str, state: str = "idle") -> None:
    """How a test ends: the chat's last turn is over, its end's hooks included. They run
    git after the state shows, and a test that left then would cancel a git command as it
    starts, which never returns. Closes the chat's run.
    """
    await reached(api, chat_id, state)
    await soon(api.ctx.sessions.close_idle_run(chat_id))


async def turn_ended(scene: Scene) -> None:
    await scene.caller.end_turn()
    await reached(scene.api, scene.caller.chat_id)


async def no_pending(scene: Scene) -> bool:
    return (await scene.api.ctx.sessions.get(scene.caller.chat_id)).pending_worktree is None


def next_codex_turn(api: Api) -> None:
    api.codex.script(note("turn/started", threadId="thread-1", turn={"id": "turn-1"}))


async def finished_report_turn(scene: Scene, reports: int = 1) -> None:
    """The caller's turn with the pixie's report ends."""

    async def arrived() -> bool:
        return len(await scene.results()) == reports and bool(scene.api.codex.transport)

    await until(arrived)
    await until(lambda: _running(scene))
    scene.api.codex.transport.push(turn_completed())
    await settled(scene.api, scene.caller.chat_id)


async def _running(scene: Scene) -> bool:
    return (await scene.detail())["state"] == "running"


async def test_a_called_pixie_removes_its_callers_worktree_when_the_turn_ends(
    scene: Scene,
) -> None:
    pixie = Pixie(scene.api, {"action": "remove", "delete_branch": True})
    path = await opened(scene)
    branch = (await scene.detail())["branch"]
    repo = scene.api.ctx.repos.get("repo").path

    calling = asyncio.create_task(scene.caller.call(pixie="coder", task="Finish it"))
    await soon(pixie.recorded.wait())
    assert pixie.refusal is None
    assert path.exists()
    pixie.go.set()
    assert await soon(calling) == "Done."
    assert path.exists()

    await turn_ended(scene)
    await settled(scene.api, scene.caller.chat_id)

    assert await no_pending(scene)
    chat = await scene.detail()
    assert not path.exists()
    assert (chat["state"], chat["worktree_path"], chat["cwd"]) == ("idle", None, str(repo))
    assert [(e["path"], e["state"]) for e in chat["earlier_worktrees"]] == [(str(path), "deleted")]
    assert git(repo, "branch", "--list", str(branch)) == ""
    [called] = await scene.called_sessions()
    assert called["cwd"] == str(repo)


async def test_a_background_pixie_keeps_its_folder_until_it_is_done(scene: Scene) -> None:
    """The caller's turn ends first: nothing goes while the pixie works, and its report
    starts the turn that applies the change.
    """
    pixie = Pixie(scene.api, {"action": "remove"})
    path = await opened(scene)

    await soon(scene.caller.call(pixie="coder", task="Finish it", run_in_background=True))
    await soon(pixie.recorded.wait())
    await turn_ended(scene)

    assert path.exists()
    assert not await no_pending(scene)
    assert pixie.run is not None
    assert not pixie.run.closed

    next_codex_turn(scene.api)
    pixie.go.set()
    await finished_report_turn(scene)

    assert await no_pending(scene)
    assert not path.exists()
    assert (await scene.detail())["worktree_path"] is None


async def test_a_background_pixie_recording_on_an_idle_caller_still_applies(scene: Scene) -> None:
    pixie = Pixie(scene.api, None)
    path = await opened(scene)
    await soon(scene.caller.call(pixie="coder", task="Finish it", run_in_background=True))
    await soon(pixie.recorded.wait())
    await turn_ended(scene)
    assert pixie.run is not None

    await tool_of(pixie.run).handler({"action": "remove"})
    assert path.exists()

    next_codex_turn(scene.api)
    pixie.go.set()
    await finished_report_turn(scene)

    assert await no_pending(scene)
    assert not path.exists()


async def test_a_pixie_stopped_after_recording_removes_nothing(scene: Scene) -> None:
    pixie = Pixie(scene.api, {"action": "remove"})
    path = await opened(scene)
    calling = asyncio.create_task(scene.caller.call(pixie="coder", task="Finish it"))
    await soon(pixie.recorded.wait())

    stopped = await scene.api.http.post(f"/api/sessions/{scene.caller.chat_id}/tasks/tu1/stop")
    assert stopped.status_code == 202, stopped.text
    await soon(calling)
    await turn_ended(scene)
    await settled(scene.api, scene.caller.chat_id)

    assert path.exists()
    assert await no_pending(scene)
    assert (await scene.detail())["worktree_path"] == str(path)


async def test_stopping_the_callers_turn_cancels_what_the_pixie_recorded(scene: Scene) -> None:
    pixie = Pixie(scene.api, {"action": "remove"})
    path = await opened(scene)
    await soon(scene.caller.call(pixie="coder", task="Finish it", run_in_background=True))
    await soon(pixie.recorded.wait())

    stopped = await scene.api.http.post(f"/api/sessions/{scene.caller.chat_id}/interrupt")
    assert stopped.status_code == 202, stopped.text
    scene.api.codex.transport.push(turn_completed(status="interrupted"))

    await settled(scene.api, scene.caller.chat_id, "interrupted")
    assert await no_pending(scene)
    assert path.exists()


async def test_another_open_chat_in_the_worktree_still_blocks_a_called_pixie(scene: Scene) -> None:
    path = await opened(scene)
    scene.api.provider.script(reply("joined"))
    joined = await create(scene.api, worktree_path=str(path), mode=None)
    await settled(scene.api, str(joined["id"]))
    pixie = Pixie(scene.api, {"action": "remove"})

    await soon(scene.caller.call(pixie="coder", task="Finish it", run_in_background=True))
    await soon(pixie.recorded.wait())

    assert pixie.refusal is not None
    assert "another" in pixie.refusal.lower()
    assert await no_pending(scene)


async def test_a_called_pixie_cannot_move_its_caller(scene: Scene) -> None:
    pixie = Pixie(scene.api, None)
    await opened(scene)
    await soon(scene.caller.call(pixie="coder", task="Finish it", run_in_background=True))
    await soon(pixie.recorded.wait())
    assert pixie.run is not None

    for action in ("new", "back", "cancel"):
        with pytest.raises(ToolRefusedError):
            await tool_of(pixie.run).handler({"action": action, "worktree": "project"})


async def test_a_caller_on_autopilot_gives_its_pixie_no_tool(scene: Scene) -> None:
    pixie = Pixie(scene.api, None)
    await opened(scene)
    switched = await scene.api.http.put(
        f"/api/sessions/{scene.caller.chat_id}/autopilot", json={"on": True}
    )
    assert switched.status_code == 200, switched.text
    await soon(scene.caller.call(pixie="coder", task="Finish it", run_in_background=True))
    await soon(pixie.recorded.wait())

    assert pixie.run is not None
    assert tools_of(pixie.run) == []


async def test_a_read_only_pixie_gets_no_worktree_tool(api: Api) -> None:
    scene = Scene(api, Called(api, "claude"), Caller(api, "codex"))
    await scene.pixie(project_access="read")
    pixie = Pixie(api, None)
    await opened(scene)
    await soon(scene.caller.call(pixie="coder", task="Finish it", run_in_background=True))
    await soon(pixie.recorded.wait())

    assert pixie.run is not None
    assert tools_of(pixie.run) == []


async def test_a_pixies_own_chat_has_no_worktree_tool(api: Api) -> None:
    scene = Scene(api, Called(api, "claude"), Caller(api, "codex"))
    pixie_id = await scene.pixie()
    api.provider.script(reply("hello"))

    response = await api.http.post(f"/api/pixies/{pixie_id}/messages", json={"text": "Hi"})

    assert response.status_code == 202, response.text
    await until(lambda: bool(api.provider.runs))
    assert tools_of(api.provider.runs[-1]) == []
