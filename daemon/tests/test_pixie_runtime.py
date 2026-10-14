from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.paths import AppPaths
from nestd.pixies.files import PixieFiles
from nestd.pixies.models import PixieSettings
from nestd.pixies.prompt import HABIT_RUN_NOTE
from nestd.pixies.runtime import PixieRuntime
from nestd.pixies.store import PixieStore
from nestd.pixies.tools import TOOL_NAMES
from nestd.providers.base import AgentTool
from nestd.repos.service import RepoService
from nestd.sessions.models import NewSession, Session, pixie_repo
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.fakes import FakeClock
from tests.git_support import init_repo


async def noop(_args: dict[str, JsonValue]) -> str:
    return ""


async def test_extras_for_a_pixie_chat(tmp_path: Path, db: Database, clock: FakeClock) -> None:
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    paths.ensure()
    repos = RepoService(paths)
    web = await repos.register(init_repo(tmp_path / "web"))
    await repos.register(init_repo(tmp_path / "api"))
    store = PixieStore(db, clock)
    files = PixieFiles(paths.pixies_dir)
    reader = await store.create(
        PixieSettings(name="Reader", project_access="read", projects=["web"]), "reader"
    )
    blind = await store.create(PixieSettings(name="Blind", project_access="none"), "blind")
    editor = await store.create(
        PixieSettings(
            name="Editor",
            skills=["review"],
            allowed_tools=["Bash(npm test:*)"],
            disallowed_tools=["WebFetch"],
        ),
        "editor",
    )
    for pixie in (reader, blind, editor):
        files.create(pixie.id, "You help.")
    sessions = SessionStore(db, clock)
    asked: list[tuple[str, str]] = []

    def nest_tools(pixie_id: str, session: Session) -> tuple[AgentTool, ...]:
        asked.append((pixie_id, session.id))
        return (AgentTool("list_sessions", "List", {"type": "object"}, noop),)

    runtime = PixieRuntime(store, files, repos, EventBus(db, clock), clock, nest_tools)

    def chat(pixie_id: str) -> NewSession:
        return NewSession(
            repo=pixie_repo(pixie_id),
            title="t",
            prompt="p",
            mode="in_place",
            cwd=files.workdir(pixie_id),
            model=None,
            effort=None,
            permission_mode="default",
            provider="fake",
            pixie_id=pixie_id,
        )

    reader_chat = await sessions.create(chat(reader.id))
    read_extras = await runtime.extras(reader_chat)
    blind_extras = await runtime.extras(await sessions.create(chat(blind.id)))
    edit_extras = await runtime.extras(await sessions.create(chat(editor.id)))

    assert read_extras.extra_dirs == (web.path,)
    assert blind_extras.extra_dirs == ()
    assert len(edit_extras.extra_dirs) == 2
    assert read_extras.write_root == files.workdir(reader.id)
    assert blind_extras.write_root == files.workdir(blind.id)
    assert edit_extras.write_root is None
    assert edit_extras.skills == ("review",)
    assert edit_extras.allowed_tools == ("Bash(npm test:*)",)
    assert edit_extras.disallowed_tools == ("WebFetch",)
    assert read_extras.skills == ()
    assert tuple(t.name for t in read_extras.tools) == (*TOOL_NAMES, "list_sessions")
    assert asked[0] == (reader.id, reader_chat.id)
    assert "your autonomy (Observe)" in read_extras.system_prompt
    assert "You are Reader (@reader)" in read_extras.system_prompt
    assert "You help." in read_extras.system_prompt


async def test_extras_refuse_a_session_that_is_not_a_pixie_chat(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    paths.ensure()
    runtime = PixieRuntime(
        PixieStore(db, clock),
        PixieFiles(paths.pixies_dir),
        RepoService(paths),
        EventBus(db, clock),
        clock,
        lambda _pixie_id, _session: (),
    )
    plain = await SessionStore(db, clock).create(
        NewSession(
            repo="web",
            title="t",
            prompt="p",
            mode="in_place",
            cwd=None,
            model=None,
            effort=None,
            permission_mode="default",
            provider="fake",
        )
    )

    with pytest.raises(ValueError, match="not a pixie chat"):
        await runtime.extras(plain)


async def test_a_habit_run_starts_from_its_habit_not_from_the_chat(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    paths.ensure()
    store = PixieStore(db, clock)
    files = PixieFiles(paths.pixies_dir)
    pixie = await store.create(PixieSettings(name="Watcher"), "watcher")
    files.create(pixie.id, "You watch.")
    bus = EventBus(db, clock)
    seen: list[str | None] = []

    def tools(_pixie_id: str, session: Session) -> tuple[AgentTool, ...]:
        seen.append(session.habit_run_id)
        return ()

    runtime = PixieRuntime(store, files, RepoService(paths), bus, clock, tools)
    run = await SessionStore(db, clock).create(
        NewSession(
            repo=pixie_repo(pixie.id),
            title="Morning check",
            prompt="p",
            mode="in_place",
            cwd=files.workdir(pixie.id),
            model=None,
            effort=None,
            permission_mode="default",
            provider="fake",
            pixie_id=pixie.id,
            habit_run_id="r1",
        )
    )
    await bus.publish(types.SESSION_USER_MESSAGE, {"text": "Run your habit"}, run.id)

    extras = await runtime.extras(run)

    assert extras.system_prompt.endswith(HABIT_RUN_NOTE)
    assert "You watch." in extras.system_prompt
    assert "## Recent conversation" not in extras.system_prompt
    assert seen == ["r1"]
