"""A chat's folder's dev server over the API (B108): routes, events, ports for setup and
the agent, and the run's end with its worktree, its repo and the daemon.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from nestd.config.loader import save_repo
from nestd.config.models import RunConfig, WorktreeConfig
from nestd.events import types
from nestd.runs.blocks import PortBlock
from nestd.runs.prompt import ports_prompt
from nestd.sessions.turns import NEST_PROMPT
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, reach

SERVE = 'echo "serving on $NEST_PORT"; echo $$ > "$NEST_PID_FILE"; exec sleep 30'

type Sent = list[tuple[str, dict[str, Any]]]


@pytest.fixture
async def api(
    tmp_path: Path,
    clock: FakeClock,
    secrets: FakeSecretStore,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Api]:
    # Where each run writes its process id, through the daemon's environment.
    monkeypatch.setenv("NEST_PID_FILE", str(tmp_path / "pid"))
    async with running_api(tmp_path, clock, secrets) as running:
        response = await running.http.post(
            "/api/repos", json={"path": str(init_repo(tmp_path / "repo"))}
        )
        assert response.status_code == 201, response.text
        configure(running, SERVE)
        yield running


def configure(
    api: Api, command: str | None, after_setup: bool = False, setup: list[str] | None = None
) -> None:
    repo = api.ctx.repos.get("repo")
    save_repo(
        api.ctx.paths,
        repo.model_copy(
            update={
                "run": None
                if command is None
                else RunConfig(command=command, after_setup=after_setup),
                "worktree": WorktreeConfig(setup=setup or []),
            }
        ),
    )


@pytest.fixture
def sent(api: Api, monkeypatch: pytest.MonkeyPatch) -> Sent:
    events: Sent = []
    publish = api.ctx.bus.publish_ephemeral

    async def record(event_type: str, payload: dict[str, Any], session_id: str | None = None):  # noqa: ANN202
        if event_type.startswith("run."):
            events.append((event_type, dict(payload)))
        return await publish(event_type, payload, session_id)

    monkeypatch.setattr(api.ctx.bus, "publish_ephemeral", record)
    return events


async def in_place_chat(api: Api) -> str:
    api.provider.script(reply("Done"))
    session = await create(api, mode="in_place")
    session_id = str(session["id"])
    await reach(api, session_id, "idle", results=1)
    return session_id


def exists(path: Path) -> bool:
    return path.exists()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def test_a_chat_runs_its_folders_dev_server_and_reads_its_output(
    api: Api, sent: Sent, tmp_path: Path
) -> None:
    session_id = await in_place_chat(api)
    run = f"/api/sessions/{session_id}/run"
    folder = str(tmp_path / "repo")

    before = await api.http.get(run)
    started = await api.http.post(f"{run}/start")
    await until(lambda: any("serving" in p.get("text", "") for _, p in sent))
    again = await api.http.post(f"{run}/start")
    output = await api.http.get(f"{run}/output")
    stopped = await api.http.post(f"{run}/stop")
    unchanged = await api.http.post(f"{run}/stop")

    assert before.status_code == 200
    assert before.json() == {
        "available": True,
        "command": SERVE,
        "folder": folder,
        "block": {"start": 41000, "end": 41009},
        "state": "stopped",
        "listening": [],
        "exit_code": None,
        "started_at": None,
    }
    assert started.status_code == 200
    assert started.json() | {"started_at": None} == before.json() | {"state": "starting"}
    assert started.json()["started_at"] == "2026-01-01T12:00:00Z"
    assert again.json() == started.json()
    assert output.json() == {"folder": folder, "text": f"$ {SERVE}\nserving on 41000\n"}
    assert stopped.json() == before.json()
    assert unchanged.json() == before.json()
    assert [kind for kind, _ in sent] == [
        types.RUN_OUTPUT,
        types.RUN_CHANGED,
        types.RUN_OUTPUT,
        types.RUN_CHANGED,
    ]
    changed = sent[1][1]
    assert (changed["folder"], changed["repo"]) == (folder, "repo")
    assert changed["status"] == started.json()


async def test_restart_runs_the_command_afresh(api: Api) -> None:
    session_id = await in_place_chat(api)
    run = f"/api/sessions/{session_id}/run"
    await api.http.post(f"{run}/start")
    configure(api, "echo again; exec sleep 30")

    restarted = await api.http.post(f"{run}/restart")
    await api.http.post(f"{run}/stop")

    assert restarted.status_code == 200
    assert (restarted.json()["state"], restarted.json()["command"]) == (
        "starting",
        "echo again; exec sleep 30",
    )


async def test_a_chat_without_a_command_cannot_start_a_run(api: Api) -> None:
    session_id = await in_place_chat(api)
    configure(api, None)
    run = f"/api/sessions/{session_id}/run"

    status = await api.http.get(run)
    start = await api.http.post(f"{run}/start")
    restart = await api.http.post(f"{run}/restart")

    assert (status.json()["available"], status.json()["command"]) == (False, None)
    assert status.json()["block"] == {"start": 41000, "end": 41009}
    assert (start.status_code, start.json()) == (
        409,
        {"detail": "this chat has no dev server command to run"},
    )
    assert restart.status_code == 409


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", ""), ("post", "/start"), ("post", "/stop"), ("post", "/restart"), ("get", "/output")],
)
async def test_the_run_of_an_unknown_chat_is_not_found(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method.upper(), f"/api/sessions/nope/run{path}")

    assert response.status_code == 404


async def test_the_agent_hears_of_its_ports_and_the_command(api: Api) -> None:
    await in_place_chat(api)

    (run,) = api.provider.runs
    assert run.spec.env["NEST_PORT"] == "41000"
    assert run.spec.env["NEST_PORT_9"] == "41009"
    assert run.spec.system_prompt_append == (
        f"{NEST_PROMPT} {ports_prompt(PortBlock(41000, 10), SERVE, None)}"
    )


async def test_a_new_worktree_sets_up_with_its_ports_and_its_run_goes_with_it(
    api: Api, sent: Sent, tmp_path: Path
) -> None:
    await in_place_chat(api)
    configure(api, SERVE, after_setup=True, setup=['echo "$NEST_PORT" > setup-port'])
    api.provider.script(reply("Done"))
    session = await create(api)
    session_id = str(session["id"])
    await reach(api, session_id, "idle", results=1)
    worktree = Path(
        str((await api.http.get(f"/api/sessions/{session_id}")).json()["worktree_path"])
    )
    await until(lambda: (tmp_path / "pid").exists())
    pid = int((tmp_path / "pid").read_text(encoding="utf-8"))
    status = (await api.http.get(f"/api/sessions/{session_id}/run")).json()
    setup_port = (worktree / "setup-port").read_text(encoding="utf-8")

    closed = await api.http.delete(f"/api/sessions/{session_id}", params={"remove_worktree": True})

    # The main checkout took the first block.
    assert setup_port == "41010\n"
    assert status["block"] == {"start": 41010, "end": 41019}
    assert (status["state"], status["folder"]) == ("starting", str(worktree))
    assert closed.status_code == 200
    assert not exists(worktree)
    await until(lambda: not process_exists(pid))
    assert [p["status"]["state"] for kind, p in sent if kind == types.RUN_CHANGED] == [
        "starting",
        "stopped",
    ]
    rows = await api.ctx.db.fetch_all("SELECT folder FROM port_blocks ORDER BY block")
    assert [row["folder"] for row in rows] == [str(tmp_path / "repo")]


async def test_setup_commands_see_the_worktrees_ports(api: Api) -> None:
    configure(api, None, setup=['echo "$NEST_PORT $NEST_PORT_9" > "$NEST_PID_FILE"'])
    api.provider.script(reply("Done"))

    session = await create(api)
    await reach(api, str(session["id"]), "idle", results=1)

    pid_file = Path(os.environ["NEST_PID_FILE"])
    assert read(pid_file) == "41000 41009\n"


async def test_removing_the_repo_stops_its_runs_and_frees_its_ports(
    api: Api, tmp_path: Path
) -> None:
    session_id = await in_place_chat(api)
    await api.http.post(f"/api/sessions/{session_id}/run/start")
    await until(lambda: (tmp_path / "pid").exists())
    pid = int((tmp_path / "pid").read_text(encoding="utf-8"))

    removed = await api.http.delete("/api/repos/repo", params={"purge_sessions": True})

    assert removed.status_code == 204
    await until(lambda: not process_exists(pid))
    assert await api.ctx.db.fetch_all("SELECT folder FROM port_blocks") == []


async def test_the_daemon_stopping_stops_every_run(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEST_PID_FILE", str(tmp_path / "pid"))
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        configure(running, SERVE)
        session_id = await in_place_chat(running)
        await running.http.post(f"/api/sessions/{session_id}/run/start")
        await until(lambda: (tmp_path / "pid").exists())
        pid = int((tmp_path / "pid").read_text(encoding="utf-8"))

    await until(lambda: not process_exists(pid))
