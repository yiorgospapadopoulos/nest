"""Each folder's dev server run (B108): real `/bin/sh` commands in a temporary folder, with
the listening ports faked instead of read with lsof.
"""

import logging
import os
import signal
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from nestd.config.loader import save_repo
from nestd.config.models import PortSettings, RepoConfig, RunConfig
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.paths import AppPaths
from nestd.providers.shell_env import no_shell_env
from nestd.repos.service import RepoService
from nestd.runs.blocks import PortBlock, PortBlocks
from nestd.runs.manager import RunManager, RunUnavailableError
from nestd.runs.prompt import ports_prompt
from nestd.sessions.models import Session, SessionState, pixie_repo
from nestd.sessions.ports import NO_PORTS
from nestd.storage.db import Database
from tests.async_support import until
from tests.fakes import START, FakeClock
from tests.test_session_store import new_session

SERVE = 'echo "port $NEST_PORT to $NEST_PORT_2"; exec sleep 30'

type Sent = list[tuple[str, dict[str, Any]]]


class FakeProbe:
    def __init__(self) -> None:
        self.ports: list[int] = []
        self.groups: set[int] = set()

    async def __call__(self, group: int) -> list[int]:
        self.groups.add(group)
        return self.ports


class Kills:
    """Records the signals sent; `real` passes them on to the process group."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, int]] = []
        self.real = True
        self.error: Exception | None = None

    def __call__(self, group: int, number: int) -> None:
        self.sent.append((group, number))
        if self.error is not None:
            raise self.error
        if self.real:
            os.killpg(group, number)


class Env:
    def __init__(self, tmp_path: Path, db: Database, clock: FakeClock) -> None:
        self.paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
        self.paths.ensure()
        self.folder = tmp_path / "web"
        self.folder.mkdir()
        self.bus = EventBus(db, clock)
        self.sent: Sent = []
        publish = self.bus.publish_ephemeral

        async def record(  # noqa: ANN202
            event_type: str, payload: Mapping[str, JsonValue], session_id: str | None = None
        ):
            self.sent.append((event_type, dict(payload)))
            return await publish(event_type, payload, session_id)

        self.bus.publish_ephemeral = record
        self.probe = FakeProbe()
        self.kills = Kills()
        self.blocks = PortBlocks(db, clock, lambda: PortSettings(start=50000, size=3, blocks=2))
        self.logs = tmp_path / "logs"
        self.runs = RunManager(
            bus=self.bus,
            blocks=self.blocks,
            repos=RepoService(self.paths, self.bus),
            clock=clock,
            logs_dir=self.logs,
            probe=self.probe,
            shell_env=no_shell_env,
            base_env=os.environ,
            poll_interval=timedelta(milliseconds=10),
            stop_grace=timedelta(milliseconds=200),
            kill=self.kills,
        )
        self.repo("web", SERVE)

    def repo(self, name: str, command: str | None, after_setup: bool = False) -> RepoConfig:
        run = None if command is None else RunConfig(command=command, after_setup=after_setup)
        repo = RepoConfig(name=name, path=self.folder, git=False, run=run)
        save_repo(self.paths, repo)
        return repo

    def session(self, **fields: object) -> Session:
        values: dict[str, object] = {"repo": "web", "mode": "in_place", "cwd": self.folder}
        values.update(fields)
        return Session(
            **new_session(**values).model_dump(),
            id="s1",
            state=SessionState.IDLE,
            worktree_path=None,
            branch=None,
            provider_session_id=None,
            created_at=START,
            updated_at=START,
            last_error=None,
        )

    def events(self, kind: str) -> list[dict[str, Any]]:
        return [payload for event_type, payload in self.sent if event_type == kind]

    def states(self) -> list[str]:
        return [payload["status"]["state"] for payload in self.events(types.RUN_CHANGED)]

    async def text(self, session: Session) -> str:
        return (await self.runs.output(session)).text


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock):  # noqa: ANN201
    made = Env(tmp_path, db, clock)
    yield made
    await made.runs.shutdown()


async def test_a_project_chat_has_its_folders_ports_and_run(env: Env) -> None:
    status = await env.runs.status(env.session())

    assert status.model_dump(mode="json") == {
        "available": True,
        "command": SERVE,
        "folder": str(env.folder),
        "block": {"start": 50000, "end": 50002},
        "state": "stopped",
        "listening": [],
        "exit_code": None,
        "started_at": None,
    }


async def test_a_run_starts_in_its_folder_with_its_ports_and_is_followed(env: Env) -> None:
    chat = env.session()

    started = await env.runs.start(chat)
    await until(lambda: "\nport" in "".join(e["text"] for e in env.events(types.RUN_OUTPUT)))
    env.probe.ports = [3000, 50001]
    await until(lambda: env.states()[-1:] == ["running"])
    running = await env.runs.status(chat)
    env.probe.ports = [50001]
    await until(lambda: len(env.states()) == 3)
    again = await env.runs.start(chat)
    stopped = await env.runs.stop(chat)

    assert (started.state, started.started_at, started.exit_code) == ("starting", START, None)
    assert (running.state, running.listening) == ("running", [3000, 50001])
    assert again.listening == [50001]
    assert (stopped.state, stopped.listening, stopped.started_at) == ("stopped", [], None)
    assert env.states() == ["starting", "running", "running", "stopped"]
    output = "".join(e["text"] for e in env.events(types.RUN_OUTPUT))
    assert output == f"$ {SERVE}\nport 50000 to 50002\n"
    assert await env.text(chat) == output
    changed = env.events(types.RUN_CHANGED)[1]
    assert (changed["folder"], changed["repo"]) == (str(env.folder), "web")
    assert changed["status"]["listening"] == [3000, 50001]
    assert changed["status"]["started_at"] == "2026-01-01T12:00:00Z"
    assert [number for _, number in env.kills.sent] == [signal.SIGTERM]
    assert env.probe.groups == {env.kills.sent[0][0]}
    (log,) = env.logs.iterdir()
    assert log.name.startswith("run-")
    assert log.read_text(encoding="utf-8") == output


async def test_a_run_that_ends_on_its_own_exited_with_its_code(env: Env) -> None:
    env.repo("web", "echo bye; exit 3")
    chat = env.session()

    await env.runs.start(chat)
    await until(lambda: env.states()[-1:] == ["exited"])
    exited = await env.runs.status(chat)
    unchanged = await env.runs.stop(chat)

    assert (exited.state, exited.exit_code, exited.started_at) == ("exited", 3, START)
    assert unchanged == exited
    assert await env.text(chat) == "$ echo bye; exit 3\nbye\n"
    assert env.kills.sent == []


async def test_restart_starts_afresh_with_the_command_as_it_is_now(env: Env) -> None:
    chat = env.session()
    await env.runs.start(chat)
    await until(lambda: "\nport" in "".join(e["text"] for e in env.events(types.RUN_OUTPUT)))
    env.repo("web", "echo second; exec sleep 30")

    restarted = await env.runs.restart(chat)
    await until(lambda: "\nsecond" in "".join(e["text"] for e in env.events(types.RUN_OUTPUT)))

    assert (restarted.state, restarted.command) == ("starting", "echo second; exec sleep 30")
    assert await env.text(chat) == "$ echo second; exec sleep 30\nsecond\n"
    assert env.states() == ["starting", "stopped", "starting"]
    (log,) = env.logs.iterdir()
    assert log.read_text(encoding="utf-8") == "$ echo second; exec sleep 30\nsecond\n"


async def test_restart_of_a_chat_that_never_ran_starts_it(env: Env) -> None:
    restarted = await env.runs.restart(env.session())

    assert restarted.state == "starting"


async def test_a_run_ignoring_sigterm_gets_sigkill(env: Env) -> None:
    env.repo("web", "trap '' TERM; echo ready; sleep 30")
    chat = env.session()
    await env.runs.start(chat)
    await until(lambda: "\nready" in "".join(e["text"] for e in env.events(types.RUN_OUTPUT)))

    stopped = await env.runs.stop(chat)

    assert stopped.state == "stopped"
    assert [number for _, number in env.kills.sent] == [signal.SIGTERM, signal.SIGKILL]


async def test_output_held_open_after_sigkill_stops_being_read(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    chat = env.session()
    await env.runs.start(chat)
    env.kills.real = False

    with caplog.at_level(logging.WARNING):
        stopped = await env.runs.stop(chat)
    group = env.kills.sent[0][0]
    os.killpg(group, signal.SIGKILL)

    assert stopped.state == "stopped"
    assert [number for _, number in env.kills.sent] == [signal.SIGTERM, signal.SIGKILL]
    assert "holds its output open" in caplog.text


async def test_a_group_that_ended_already_is_not_an_error(env: Env) -> None:
    chat = env.session()
    await env.runs.start(chat)
    group_kill = env.kills
    group_kill.real = False
    group_kill.error = ProcessLookupError()

    # Nothing is signalled, so the run is cut off after the grace times.
    stopped = await env.runs.stop(chat)
    os.killpg(group_kill.sent[0][0], signal.SIGKILL)

    assert stopped.state == "stopped"


@pytest.mark.parametrize(
    "fields",
    [
        {"pixie_id": "p1", "repo": pixie_repo("p1")},
        {"repo": pixie_repo("p1")},
        {"cwd": None, "mode": "worktree"},
        {"repo": "docs"},
        {"repo": "gone"},
    ],
)
async def test_a_chat_without_a_run_has_none_to_start(env: Env, fields: dict[str, object]) -> None:
    env.repo("docs", None)
    chat = env.session(**fields)

    status = await env.runs.status(chat)
    with pytest.raises(RunUnavailableError):
        await env.runs.start(chat)
    with pytest.raises(RunUnavailableError):
        await env.runs.restart(chat)

    assert (status.available, status.command, status.state) == (False, None, "stopped")
    assert await env.runs.stop(chat) == status
    assert (await env.runs.output(chat)).text == ""


async def test_a_pixie_chat_has_no_folder_or_ports(env: Env) -> None:
    chat = env.session(pixie_id="p1", repo=pixie_repo("p1"))

    status = await env.runs.status(chat)

    assert (status.folder, status.block) == (None, None)
    assert await env.runs.agent_ports(chat) is NO_PORTS
    assert (await env.runs.output(chat)).folder is None


async def test_a_missing_folder_has_no_run_or_ports(env: Env, tmp_path: Path) -> None:
    chat = env.session(cwd=tmp_path / "gone")

    status = await env.runs.status(chat)

    assert (status.available, status.folder, status.block) == (False, str(tmp_path / "gone"), None)


async def test_a_repo_without_a_command_still_has_ports(env: Env) -> None:
    env.repo("web", None)

    status = await env.runs.status(env.session())
    ports = await env.runs.agent_ports(env.session())

    assert (status.available, status.block) == (False, status.block)
    assert status.block is not None
    assert ports.env == {"NEST_PORT": "50000", "NEST_PORT_1": "50001", "NEST_PORT_2": "50002"}
    assert ports.prompt == ports_prompt(PortBlock(50000, 3), None, None)


async def test_the_agent_hears_of_the_ports_the_command_and_where_it_listens(env: Env) -> None:
    chat = env.session()
    stopped = await env.runs.agent_ports(chat)
    await env.runs.start(chat)
    starting = await env.runs.agent_ports(chat)
    env.probe.ports = [50002, 50003]
    await until(lambda: env.states()[-1:] == ["running"])
    running = await env.runs.agent_ports(chat)

    block = PortBlock(50000, 3)
    assert stopped.prompt == ports_prompt(block, SERVE, None)
    assert starting.prompt == stopped.prompt
    assert running.prompt == ports_prompt(block, SERVE, 50002)
    assert running.env["NEST_PORT"] == "50000"


async def test_a_live_run_keeps_its_command_when_the_repo_drops_it(env: Env) -> None:
    chat = env.session()
    await env.runs.start(chat)
    env.repo("web", None)

    alive = await env.runs.status(chat)
    stopped = await env.runs.stop(chat)

    assert (alive.available, alive.command) == (True, SERVE)
    assert (stopped.available, stopped.command) == (False, None)


async def test_a_new_worktree_gets_ports_for_setup_and_starts_its_run_when_asked(
    env: Env, tmp_path: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    plain = env.repo("web", SERVE)
    eager = env.repo("web", SERVE, after_setup=True)
    without = env.repo("web", None)

    setup = await env.runs.setup_env(plain, worktree)
    await env.runs.set_up(plain, worktree)
    await env.runs.set_up(without, worktree)
    nothing_yet = env.states()
    await env.runs.set_up(eager, worktree)
    status = await env.runs.status(env.session(cwd=worktree))

    assert setup == {"NEST_PORT": "50000", "NEST_PORT_1": "50001", "NEST_PORT_2": "50002"}
    assert nothing_yet == []
    assert (status.state, status.folder) == ("starting", str(worktree))
    assert status.block is not None
    assert status.block.start == 50000


async def test_without_a_free_block_setup_gets_no_ports(env: Env, tmp_path: Path) -> None:
    repo = env.repo("web", SERVE)
    for name in ("a", "b"):
        await env.runs.setup_env(repo, tmp_path / name)

    assert await env.runs.setup_env(repo, tmp_path / "c") == {}


async def test_a_run_that_cannot_start_after_setup_is_logged(
    env: Env, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    eager = env.repo("web", SERVE, after_setup=True)

    with caplog.at_level(logging.WARNING):
        await env.runs.set_up(eager, tmp_path / "missing")

    assert "could not start the run in" in caplog.text
    assert env.states() == []


async def test_removing_a_worktree_stops_its_run_and_frees_its_ports(
    env: Env, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    chat = env.session()
    await env.runs.start(chat)
    await env.runs.status(env.session(cwd=other))

    await env.runs.removing(env.folder)
    await env.runs.removing(tmp_path / "never-used")

    assert env.states() == ["starting", "stopped"]
    assert await env.blocks.folders("web") == [str(other)]
    # The folder gets the lowest free block again, here its own.
    assert (await env.runs.status(chat)).state == "stopped"


async def test_removing_a_repo_stops_its_runs_and_frees_its_ports(env: Env, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    await env.runs.start(env.session())
    await env.runs.status(env.session(cwd=other))

    await env.runs.forget_repo("web")

    assert env.states() == ["starting", "stopped"]
    assert await env.blocks.folders("web") == []


async def test_shutdown_stops_every_run_and_logs_a_failure(
    env: Env, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    await env.runs.start(env.session())
    await env.runs.start(env.session(cwd=other))
    await env.runs.stop(env.session(cwd=other))
    env.kills.error = PermissionError("not allowed")

    with caplog.at_level(logging.ERROR):
        await env.runs.shutdown()
    group = env.kills.sent[-1][0]
    env.kills.error = None
    await env.runs.shutdown()

    assert "stopping the run in" in caplog.text
    assert (await env.runs.status(env.session())).state == "stopped"
    assert group == env.kills.sent[-1][0]


def test_the_ports_paragraph_names_the_ports_command_and_address() -> None:
    assert ports_prompt(PortBlock(41020, 10), None, None) == (
        "This folder's ports are 41020 to 41029: NEST_PORT is 41020 and NEST_PORT_1 to "
        "NEST_PORT_9 are the next ones, also set in your environment. Use them for anything "
        "you start that listens on a port."
    )
    assert ports_prompt(PortBlock(41020, 2), None, None) == (
        "This folder's ports are 41020 to 41021: NEST_PORT is 41020 and NEST_PORT_1 is the "
        "next one, also set in your environment. Use them for anything you start that "
        "listens on a port."
    )
    assert ports_prompt(PortBlock(41020, 1), "npm run dev", 41020) == (
        "This folder's port is 41020: NEST_PORT, also set in your environment. Use it for "
        "anything you start that listens on a port. The project's dev server command is "
        "`npm run dev`; the user starts and stops it with the Run button. It is running and "
        "listening on http://localhost:41020."
    )
    assert ports_prompt(PortBlock(41020, 1), "npm run dev", None).endswith("with the Run button.")


async def test_a_character_split_between_reads_comes_whole(env: Env) -> None:
    env.repo("web", r"printf '\342'; sleep 0.3; printf '\202\254\n'; exec sleep 30")
    chat = env.session()

    await env.runs.start(chat)
    await until(lambda: "€" in "".join(e["text"] for e in env.events(types.RUN_OUTPUT)))

    texts = [e["text"] for e in env.events(types.RUN_OUTPUT)]
    assert texts[1:] == ["€\n"]


async def test_setup_finishing_twice_starts_one_run(env: Env) -> None:
    eager = env.repo("web", SERVE, after_setup=True)

    await env.runs.set_up(eager, env.folder)
    await env.runs.set_up(eager, env.folder)

    assert env.states() == ["starting"]
