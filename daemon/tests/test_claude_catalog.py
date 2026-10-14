import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.claude_sessions import catalog as catalog_module
from nestd.claude_sessions.archive import ChatArchive
from nestd.claude_sessions.catalog import ClaudeChats
from nestd.claude_sessions.errors import ClaudeChatNotFoundError
from nestd.claude_sessions.live import LiveChats
from nestd.claude_sessions.location import candidate_dirs, encode_folder
from nestd.claude_sessions.transcript import Transcript, read_transcript
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.paths import AppPaths
from nestd.repos.service import RepoNotFoundError, RepoService
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.async_support import until
from tests.claude_support import (
    CHAT_A,
    CHAT_B,
    CHAT_C,
    ClaudeHome,
    assistant,
    simple_chat,
    text,
    user,
)
from tests.fakes import FakeClock
from tests.git_support import init_repo
from tests.test_session_store import new_session

T1 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
T3 = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)


class Setup:
    def __init__(self, tmp_path: Path, db: Database, clock: FakeClock) -> None:
        self.paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
        self.paths.ensure()
        self.claude = ClaudeHome(tmp_path / "claude")
        self.repos = RepoService(self.paths)
        self.store = SessionStore(db, clock)
        self.bus = EventBus(db, clock)
        self.archive = ChatArchive(db, clock)
        self.alive: set[int] = set()
        self.published: list[tuple[str, Mapping[str, JsonValue]]] = []
        self.root = init_repo(tmp_path / "repo").resolve()
        self.chats = self.build(self.claude.root)

    def build(
        self, claude_dir: Path | None, interval: timedelta = timedelta(hours=1)
    ) -> ClaudeChats:
        return ClaudeChats(
            claude_dir=claude_dir,
            repos=self.repos,
            store=self.store,
            archive=self.archive,
            bus=self.bus,
            live=LiveChats(self.claude.root, alive=lambda pid: pid in self.alive),
            interval=interval,
        )

    def worktree(self, name: str) -> Path:
        return self.root / ".claude" / "worktrees" / name


@pytest.fixture
async def setup(
    tmp_path: Path, db: Database, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Setup]:
    environment = Setup(tmp_path, db, clock)
    await environment.repos.register(environment.root)

    async def record(
        event_type: str, payload: Mapping[str, JsonValue], session_id: str | None = None
    ) -> None:
        assert session_id is None
        environment.published.append((event_type, payload))

    monkeypatch.setattr(environment.bus, "publish_ephemeral", record)
    yield environment
    await environment.chats.stop()


async def test_lists_chats_of_the_repo_and_its_claude_worktrees(setup: Setup) -> None:
    claude = setup.claude
    claude.write_chat(setup.root, CHAT_A, simple_chat(), modified=T1)
    claude.write_chat(
        setup.worktree("agent-x"),
        CHAT_B,
        [*simple_chat("Add dark mode"), {"type": "custom-title", "customTitle": "Dark mode"}],
        modified=T2,
    )
    claude.open_chat(99, CHAT_B, entrypoint="cli")
    setup.alive.add(99)

    chats = await setup.chats.list_chats()

    assert [chat.model_dump() for chat in chats] == [
        {
            "id": CHAT_B,
            "repo": "repo",
            "title": "Dark mode",
            "cwd": setup.worktree("agent-x"),
            "worktree": "agent-x",
            "created_at": datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
            "last_activity_at": T2,
            "message_count": 2,
            "open_in_claude_code": True,
            "entrypoint": None,
            "automated": False,
            "archived": False,
        },
        {
            "id": CHAT_A,
            "repo": "repo",
            "title": "Fix the login bug",
            "cwd": setup.root,
            "worktree": None,
            "created_at": datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
            "last_activity_at": T1,
            "message_count": 2,
            "open_in_claude_code": False,
            "entrypoint": None,
            "automated": False,
            "archived": False,
        },
    ]


async def test_leaves_out_what_is_not_a_claude_code_chat_of_the_repo(
    setup: Setup, tmp_path: Path
) -> None:
    claude = setup.claude
    root = setup.root
    # Nest's own worktree, another folder with the same prefix, a subfolder.
    claude.write_chat(setup.worktree("nest-0123abcd"), CHAT_A, simple_chat())
    # B43: one of its worktrees from before the rename.
    claude.write_chat(
        setup.worktree("harness-89abcdef"), "aaaaaaaa-1111-4000-8000-000000000009", simple_chat()
    )
    claude.write_chat(root.parent / f"{root.name}-old", CHAT_B, simple_chat())
    claude.write_chat(root / "src", CHAT_C, simple_chat())
    project = claude.project_dir(root)
    # Not a session id, no prompt, no cwd, not a transcript.
    claude.write_chat(root, "notes", simple_chat())
    claude.write_chat(root, "dddddddd-0000-4000-8000-000000000004", [{"type": "queue-operation"}])
    (project / "eeeeeeee-0000-4000-8000-000000000005.jsonl").write_text(
        '{"type": "user", "uuid": "u", "message": {"content": "No cwd"}}\n', encoding="utf-8"
    )
    (project / "memory").mkdir()
    (claude.projects / "stray.jsonl").write_text("", encoding="utf-8")
    # A chat the user later adopted into Nest.
    owned = "ffffffff-0000-4000-8000-000000000006"
    claude.write_chat(root, owned, simple_chat())
    session = await setup.store.create(new_session(mode="in_place", cwd=root))
    await setup.store.update(session.id, provider_session_id=owned)
    # A conversation that session had before /clear (BUG-41).
    cleared = "ffffffff-0000-4000-8000-000000000007"
    claude.write_chat(root, cleared, simple_chat())
    await setup.store.keep_earlier_provider_session(session.id, cleared)

    assert await setup.chats.list_chats() == []


async def test_chats_recorded_under_a_linked_old_path_belong_to_the_repo(
    setup: Setup, tmp_path: Path
) -> None:
    # B43: the folder was renamed and the old path is now a link to it.
    old = tmp_path / "old-name"
    old.symlink_to(setup.root, target_is_directory=True)
    (setup.root / ".claude" / "worktrees" / "agent-x").mkdir(parents=True)
    claude = setup.claude
    project = claude.project_dir(setup.root)
    claude.write_chat(old, CHAT_A, simple_chat(), modified=T1, directory=project)
    worktree = old / ".claude" / "worktrees" / "agent-x"
    claude.write_chat(worktree, CHAT_B, simple_chat(), modified=T2, directory=project)
    # A worktree removed since: its path no longer exists.
    gone = old / ".claude" / "worktrees" / "gone"
    claude.write_chat(gone, CHAT_C, simple_chat(), modified=T3, directory=project)
    # Still left out: Nest's own worktree and a folder that no longer exists elsewhere.
    owned = old / ".claude" / "worktrees" / "nest-0123abcd"
    claude.write_chat(
        owned, "aaaaaaaa-1111-4000-8000-000000000008", simple_chat(), directory=project
    )
    missing = tmp_path / "missing"
    claude.write_chat(
        missing, "aaaaaaaa-1111-4000-8000-000000000009", simple_chat(), directory=project
    )

    chats = await setup.chats.list_chats()

    assert [(chat.id, chat.cwd, chat.worktree) for chat in chats] == [
        (CHAT_C, gone, "gone"),
        (CHAT_B, worktree, "agent-x"),
        (CHAT_A, old, None),
    ]


def test_project_dirs_of_a_linked_folder_include_its_target(tmp_path: Path) -> None:
    target = tmp_path / "new-name"
    target.mkdir()
    link = tmp_path / "old-name"
    link.symlink_to(target, target_is_directory=True)
    projects = tmp_path / "projects"
    for folder in (link, target, tmp_path / "other"):
        (projects / encode_folder(folder)).mkdir(parents=True)

    assert candidate_dirs(projects, link) == [
        projects / encode_folder(target),
        projects / encode_folder(link),
    ]
    assert candidate_dirs(projects, target) == [projects / encode_folder(target)]


async def test_chats_of_one_repo(setup: Setup, tmp_path: Path) -> None:
    other = init_repo(tmp_path / "other").resolve()
    await setup.repos.register(other)
    setup.claude.write_chat(setup.root, CHAT_A, simple_chat())
    setup.claude.write_chat(other, CHAT_B, simple_chat())

    assert [chat.id for chat in await setup.chats.list_chats("other")] == [CHAT_B]
    with pytest.raises(RepoNotFoundError):
        await setup.chats.list_chats("missing")


async def test_automated_chats_are_hidden_unless_asked_for(setup: Setup) -> None:
    claude = setup.claude
    claude.write_chat(
        setup.root, CHAT_A, [user("u1", "Review this change", entrypoint="sdk-py")], modified=T1
    )
    claude.write_chat(
        setup.root, CHAT_B, [user("u1", "Fix the bug", entrypoint="claude-desktop")], modified=T2
    )
    claude.write_chat(setup.root, CHAT_C, [user("u1", "Explain", entrypoint="cli")], modified=T3)

    shown = await setup.chats.list_chats()
    every = await setup.chats.list_chats(include_automated=True)

    assert [(chat.id, chat.entrypoint) for chat in shown] == [
        (CHAT_C, "cli"),
        (CHAT_B, "claude-desktop"),
    ]
    assert [(chat.id, chat.automated) for chat in every] == [
        (CHAT_C, False),
        (CHAT_B, False),
        (CHAT_A, True),
    ]
    assert [chat.id for chat in await setup.chats.list_chats("repo")] == [CHAT_C, CHAT_B]
    # One chat is reachable by id either way.
    assert (await setup.chats.get(CHAT_A)).automated is True


async def test_nothing_without_claude_code_data(setup: Setup) -> None:
    assert await setup.build(None).list_chats() == []
    assert await setup.chats.list_chats() == []  # no projects folder yet


async def test_a_chat_in_two_folders_shows_once_with_the_newest_copy(setup: Setup) -> None:
    setup.claude.write_chat(setup.root, CHAT_A, simple_chat("Old copy"), modified=T2)
    setup.claude.write_chat(setup.worktree("agent-y"), CHAT_A, simple_chat("New copy"), modified=T3)
    setup.claude.write_chat(setup.worktree("agent-z"), CHAT_A, simple_chat("Older"), modified=T1)

    (chat,) = await setup.chats.list_chats()

    assert (chat.title, chat.worktree) == ("New copy", "agent-y")


async def test_only_changed_files_are_read_again(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[Path] = []

    def counting(path: Path) -> Transcript:
        reads.append(path)
        return read_transcript(path)

    monkeypatch.setattr(catalog_module, "read_transcript", counting)
    first = setup.claude.write_chat(setup.root, CHAT_A, simple_chat(), modified=T1)
    second = setup.claude.write_chat(setup.root, CHAT_B, simple_chat("Second"), modified=T1)
    await setup.chats.list_chats()
    await setup.chats.list_chats()
    setup.claude.write_chat(setup.root, CHAT_A, simple_chat("Renamed"), modified=T2)
    second.unlink()

    (chat,) = await setup.chats.list_chats()

    assert chat.title == "Renamed"
    assert sorted(reads) == sorted([first, second, first])


async def test_unreadable_transcripts_are_skipped(setup: Setup) -> None:
    path = setup.claude.write_chat(setup.root, CHAT_A, simple_chat())
    path.chmod(0)
    try:
        assert await setup.chats.list_chats() == []
    finally:
        path.chmod(0o600)


async def test_changes_are_announced_per_repo(setup: Setup) -> None:
    claude = setup.claude
    await setup.chats.refresh()
    claude.write_chat(setup.root, CHAT_A, simple_chat(), modified=T1)
    await setup.chats.refresh()
    await setup.chats.refresh()
    claude.write_chat(setup.root, CHAT_A, [*simple_chat(), user("u2", "More", "a1")], modified=T2)
    await setup.chats.refresh()
    claude.open_chat(7, CHAT_A)
    setup.alive.add(7)
    await setup.chats.refresh()

    assert setup.published == [(types.CLAUDE_CHATS_UPDATED, {"repos": ["repo"]})] * 3


async def test_get_history_and_import(setup: Setup) -> None:
    entries = [
        user("u1", "Explain the build", timestamp=None),
        assistant("a1", [text("It uses Vite.")], "u1"),
    ]
    setup.claude.write_chat(setup.root, CHAT_A, entries, modified=T1)
    titled_only = [{"type": "custom-title", "customTitle": "Named but empty"}]
    setup.claude.write_chat(setup.root, CHAT_B, titled_only, modified=T2)

    chat = await setup.chats.get(CHAT_A)
    history = await setup.chats.history(CHAT_A)
    imported = await setup.chats.importable(CHAT_A)
    empty = await setup.chats.importable(CHAT_B)

    assert chat.title == "Explain the build"
    assert [(e.id, e.type, e.ts, e.session_id) for e in history] == [
        (1, types.SESSION_USER_MESSAGE, chat.created_at, CHAT_A),
        (2, types.SESSION_MESSAGE, datetime(2026, 10, 5, 9, 1, tzinfo=UTC), CHAT_A),
    ]
    assert history[0].payload == {"text": "Explain the build", "attachments": []}
    assert (imported.repo, imported.title, imported.prompt) == (
        "repo",
        "Explain the build",
        "Explain the build",
    )
    assert imported.cwd == setup.root
    assert imported.provider_session_id == CHAT_A
    assert imported.history == [(e.type, e.payload) for e in history]
    assert (empty.prompt, empty.history) == ("Named but empty", [])


async def test_unknown_or_vanished_chats_are_not_found(setup: Setup) -> None:
    path = setup.claude.write_chat(setup.root, CHAT_A, simple_chat())
    await setup.chats.list_chats()
    path.chmod(0)
    try:
        with pytest.raises(ClaudeChatNotFoundError, match="can no longer be read"):
            await setup.chats.history(CHAT_A)
    finally:
        path.chmod(0o600)
    with pytest.raises(ClaudeChatNotFoundError, match="unknown Claude Code chat"):
        await setup.chats.get(CHAT_B)


async def test_polling_announces_new_chats_and_survives_errors(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    chats = setup.build(setup.claude.root, interval=timedelta(milliseconds=5))
    real = setup.store.provider_session_ids
    calls: list[int] = []

    async def flaky() -> set[str]:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database busy")
        return await real()

    monkeypatch.setattr(setup.store, "provider_session_ids", flaky)
    setup.claude.write_chat(setup.root, CHAT_A, simple_chat())

    with caplog.at_level(logging.ERROR):
        await chats.start()
        await until(lambda: bool(setup.published))
        await chats.stop()
        await chats.stop()

    assert setup.published == [(types.CLAUDE_CHATS_UPDATED, {"repos": ["repo"]})]
    assert "reading Claude Code chats failed" in caplog.text
    await asyncio.sleep(0.02)
    assert len(setup.published) == 1


async def test_archiving_marks_the_chat_and_announces_its_repo(
    setup: Setup, clock: FakeClock, db: Database
) -> None:
    setup.claude.write_chat(setup.root, CHAT_A, simple_chat(), modified=T2)
    setup.claude.write_chat(setup.root, CHAT_B, simple_chat("Second"), modified=T1)
    await setup.chats.refresh()
    setup.published.clear()

    archived = await setup.chats.set_archived(CHAT_A, archived=True)
    clock.advance(timedelta(hours=1))
    again = await setup.chats.set_archived(CHAT_A, archived=True)
    listed = await setup.chats.list_chats("repo")
    row = await db.fetch_one(
        "SELECT archived_at FROM claude_chat_archive WHERE chat_id = ?", (CHAT_A,)
    )

    assert (archived.id, archived.archived, again.archived) == (CHAT_A, True, True)
    # Archived chats stay in the list, marked, for clients to group.
    assert [(chat.id, chat.archived) for chat in listed] == [(CHAT_A, True), (CHAT_B, False)]
    # Archiving again changes nothing: no second event, the first archive time stays.
    assert setup.published == [(types.CLAUDE_CHATS_UPDATED, {"repos": ["repo"]})]
    assert row is not None
    assert datetime.fromisoformat(row["archived_at"]) == clock.now() - timedelta(hours=1)

    restored = await setup.chats.set_archived(CHAT_A, archived=False)
    await setup.chats.set_archived(CHAT_A, archived=False)

    assert restored.archived is False
    assert setup.published == [(types.CLAUDE_CHATS_UPDATED, {"repos": ["repo"]})] * 2
    assert await db.fetch_all("SELECT * FROM claude_chat_archive") == []


async def test_archive_state_outlives_the_catalog(setup: Setup) -> None:
    setup.claude.write_chat(setup.root, CHAT_A, simple_chat())
    await setup.chats.set_archived(CHAT_A, archived=True)

    (chat,) = await setup.build(setup.claude.root).list_chats()

    assert chat.archived is True


async def test_archiving_an_unknown_chat_is_not_found(setup: Setup) -> None:
    with pytest.raises(ClaudeChatNotFoundError, match="unknown Claude Code chat"):
        await setup.chats.set_archived(CHAT_A, archived=True)

    assert await setup.archive.archived_ids() == set()
