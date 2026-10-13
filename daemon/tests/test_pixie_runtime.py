from pathlib import Path

import pytest

from harness.events.bus import EventBus
from harness.paths import AppPaths
from harness.pixies.files import PixieFiles
from harness.pixies.models import PixieSettings
from harness.pixies.runtime import PixieRuntime
from harness.pixies.store import PixieStore
from harness.pixies.tools import TOOL_NAMES
from harness.repos.service import RepoService
from harness.sessions.models import NewSession, pixie_repo
from harness.sessions.store import SessionStore
from harness.storage.db import Database
from tests.fakes import FakeClock
from tests.git_support import init_repo


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
    runtime = PixieRuntime(store, files, repos, EventBus(db, clock), clock)

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

    read_extras = await runtime.extras(await sessions.create(chat(reader.id)))
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
    assert tuple(t.name for t in read_extras.tools) == TOOL_NAMES
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
