"""B113: Codex chats started outside Nest, listed beside the Claude Code chats."""

import logging
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.claude_sessions.archive import ChatArchive
from nestd.claude_sessions.catalog import ClaudeChats
from nestd.claude_sessions.live import LiveChats
from nestd.codex_chats.catalog import CodexChats
from nestd.codex_chats.history import thread_history
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.paths import AppPaths
from nestd.providers.codex_process import CodexLaunch
from nestd.repos.service import RepoService
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.codex_support import CodexThreads, FakeAppServer, exchange
from tests.fakes import FakeClock
from tests.git_support import git, init_repo
from tests.test_session_store import new_session

THREAD_A = "019a0000-0000-7000-8000-00000000000a"
THREAD_B = "019a0000-0000-7000-8000-00000000000b"


class Setup:
    def __init__(self, tmp_path: Path, db: Database, clock: FakeClock) -> None:
        self.paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
        self.paths.ensure()
        self.clock = clock
        self.repos = RepoService(self.paths)
        self.store = SessionStore(db, clock)
        self.bus = EventBus(db, clock)
        self.archive = ChatArchive(db, clock)
        self.root = init_repo(tmp_path / "repo").resolve()
        self.home = tmp_path / "codex"
        self.rollout = self.home / "sessions" / "2026" / "10" / "27" / "rollout-a.jsonl"
        self.rollout.parent.mkdir(parents=True)
        self.rollout.write_text("{}\n", encoding="utf-8")
        self.server = FakeAppServer()
        self.threads = CodexThreads(self.server)
        self.published: list[tuple[str, Mapping[str, JsonValue]]] = []
        self.chats = ClaudeChats(
            claude_dir=None,
            repos=self.repos,
            store=self.store,
            archive=self.archive,
            bus=self.bus,
            live=LiveChats(None),
            codex=CodexChats(
                codex_home=self.home,
                transport=self.server,
                launch=lambda: CodexLaunch(("codex", "app-server"), {}),
                clock=clock,
            ),
        )

    def worktree(self, name: str) -> Path:
        """A git worktree of the repo outside it, as the Codex app makes them."""
        path = self.root.parent / "codex-worktrees" / name
        git(self.root, "worktree", "add", "-q", "-b", name, str(path))
        return path.resolve()

    def lists(self) -> int:
        return len(self.server.requests("thread/list"))


@pytest.fixture
async def setup(
    tmp_path: Path, db: Database, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Setup]:
    environment = Setup(tmp_path, db, clock)
    await environment.repos.register(environment.root)

    async def record(
        event_type: str, payload: Mapping[str, JsonValue], session_id: str | None = None
    ) -> None:
        environment.published.append((event_type, payload))

    monkeypatch.setattr(environment.bus, "publish_ephemeral", record)
    yield environment
    await environment.chats.stop()


async def test_lists_codex_chats_of_the_repo_and_its_git_worktrees(setup: Setup) -> None:
    root, threads = setup.root, setup.threads
    worktree = setup.worktree("dark-mode")
    threads.add(THREAD_A, root, turns=[exchange(), exchange("And the tests", "Added.")])
    threads.add(THREAD_B, worktree, name="Dark mode", source="vscode", updatedAt=1790007200)

    chats = await setup.chats.list_chats()

    assert [chat.model_dump(mode="json") for chat in chats] == [
        {
            "id": THREAD_B,
            "repo": "repo",
            "title": "Dark mode",
            "cwd": str(worktree),
            "worktree": "dark-mode",
            "created_at": "2026-09-21T14:13:20Z",
            "last_activity_at": "2026-09-21T16:13:20Z",
            "message_count": 2,
            "open_in_claude_code": False,
            "entrypoint": "vscode",
            "automated": False,
            "archived": False,
            "engine": "codex",
        },
        {
            "id": THREAD_A,
            "repo": "repo",
            # Its first prompt, by the title rules of Claude Code chats (D022).
            "title": "Fix the login bug please",
            "cwd": str(root),
            "worktree": None,
            "created_at": "2026-09-21T14:13:20Z",
            "last_activity_at": "2026-09-21T15:13:20Z",
            "message_count": 4,
            "open_in_claude_code": False,
            "entrypoint": "cli",
            "automated": False,
            "archived": False,
            "engine": "codex",
        },
    ]
    # Every source but sub-agents, archived and not, one page after another.
    listed = setup.server.requests("thread/list")
    assert [(p["archived"], p["cursor"]) for p in listed] == [
        (False, None),
        (False, "1"),
        (True, None),
    ]
    assert listed[0]["sourceKinds"] == ["cli", "vscode", "exec", "appServer", "unknown"]
    assert setup.published == [(types.CLAUDE_CHATS_UPDATED, {"repos": ["repo"]})]


async def test_leaves_out_what_is_not_a_codex_chat_of_the_repo(setup: Setup) -> None:
    root, threads = setup.root, setup.threads
    (root / "web").mkdir()
    threads.add("in-a-subfolder", root / "web")
    threads.add("in-nests-worktree", setup.worktree("nest-0123abcd"))
    threads.add("elsewhere", root.parent / "other")
    threads.add("sub-agent", root, parentThreadId=THREAD_A)
    threads.add("spawned", root, source={"subAgent": {"thread_spawn": {}}})
    threads.add("ephemeral", root, ephemeral=True)
    threads.add("no-prompt-yet", root, preview="", name=None)
    threads.add("owned", root)
    session = await setup.store.create(new_session(mode="in_place", cwd=root))
    await setup.store.update(session.id, provider_session_id="owned")

    assert await setup.chats.list_chats(include_automated=True) == []
    # Nothing of theirs is read but the list.
    assert setup.server.requests("thread/turns/list") == []


async def test_program_and_nest_started_chats_are_automated(setup: Setup) -> None:
    root, threads = setup.root, setup.threads
    threads.add("typed", root)
    threads.add("exec", root, source="exec")
    threads.add("app-server", root, source="appServer")
    threads.add("custom", root, source={"custom": "my-tool"})
    threads.add("nests-deleted-chat", root, originator="nest", source="vscode")

    assert [chat.id for chat in await setup.chats.list_chats()] == ["typed"]
    every = {chat.id: chat for chat in await setup.chats.list_chats(include_automated=True)}
    assert {chat_id for chat_id, chat in every.items() if chat.automated} == {
        "exec",
        "app-server",
        "custom",
        "nests-deleted-chat",
    }
    assert every["custom"].entrypoint == "custom"


async def test_archiving_goes_through_codex_and_its_state_comes_back(setup: Setup) -> None:
    threads = setup.threads
    threads.add(THREAD_A, setup.root)
    threads.add(THREAD_B, setup.root, archived=True)
    before = await setup.chats.list_chats()
    assert {chat.id: chat.archived for chat in before} == {THREAD_A: False, THREAD_B: True}
    setup.published.clear()

    archived = await setup.chats.set_archived(THREAD_A, archived=True)

    assert archived.archived is True
    assert setup.server.requests("thread/archive") == [{"threadId": THREAD_A}]
    assert threads.archived[-1]["id"] == THREAD_A
    assert setup.published == [(types.CLAUDE_CHATS_UPDATED, {"repos": ["repo"]})]
    # Nest keeps no archive of its own for Codex chats.
    assert await setup.archive.archived_ids() == set()
    # Again: Codex is not asked.
    await setup.chats.set_archived(THREAD_A, archived=True)
    assert len(setup.server.requests("thread/archive")) == 1

    restored = await setup.chats.set_archived(THREAD_B, archived=False)

    assert restored.archived is False
    assert setup.server.requests("thread/unarchive") == [{"threadId": THREAD_B}]


async def test_codex_is_asked_again_only_when_its_files_change(
    setup: Setup, clock: FakeClock
) -> None:
    setup.threads.add(THREAD_A, setup.root)
    await setup.chats.list_chats()
    await setup.chats.list_chats()
    assert setup.lists() == 2  # one pass: the active list and the archived one
    assert len(setup.server.requests("thread/turns/list")) == 1

    setup.threads.add(THREAD_B, setup.root, updatedAt=1790009000)
    setup.rollout.write_text("{}\n{}\n", encoding="utf-8")
    chats = await setup.chats.list_chats()

    assert [chat.id for chat in chats] == [THREAD_B, THREAD_A]
    assert setup.lists() == 5
    # The unchanged chat's messages are not counted again.
    assert [p["threadId"] for p in setup.server.requests("thread/turns/list")] == [
        THREAD_A,
        THREAD_B,
    ]

    clock.advance(timedelta(minutes=5))
    await setup.chats.list_chats()
    assert setup.lists() == 8


async def test_a_failing_codex_keeps_the_last_list_and_warns_once(
    setup: Setup, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    setup.threads.add(THREAD_A, setup.root)
    await setup.chats.list_chats()
    setup.server.errors["thread/list"] = (-32603, "secret output")
    caplog.set_level(logging.WARNING)

    for _ in range(2):
        clock.advance(timedelta(minutes=5))
        assert [chat.id for chat in await setup.chats.list_chats()] == [THREAD_A]

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == ["reading Codex chats failed (Codex could not be asked (CodexRpcError))"]


async def test_without_a_codex_home_there_are_no_codex_chats_and_no_warning(
    setup: Setup, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    """B117: Codex never used here (no ~/.codex, as on a fresh Linux install) is not a
    failure: nothing is asked and nothing is logged, however often chats are listed."""
    missing = setup.home.parent / "no-codex"
    setup.chats = ClaudeChats(
        claude_dir=None,
        repos=setup.repos,
        store=setup.store,
        archive=setup.archive,
        bus=setup.bus,
        live=LiveChats(None),
        codex=CodexChats(
            codex_home=missing,
            transport=setup.server,
            launch=lambda: CodexLaunch(("codex", "app-server"), {"CODEX_HOME": str(missing)}),
            clock=clock,
        ),
    )
    caplog.set_level(logging.WARNING)

    for _ in range(3):
        clock.advance(timedelta(minutes=5))
        assert await setup.chats.list_chats() == []

    assert setup.server.launches == []
    assert caplog.records == []


async def test_history_and_import_of_a_codex_chat(setup: Setup) -> None:
    setup.threads.add(THREAD_A, setup.root, model="gpt-5.5")

    events = await setup.chats.history(THREAD_A)
    imported = await setup.chats.importable(THREAD_A)

    assert [(e.id, e.type, e.ts) for e in events] == [
        (1, types.SESSION_USER_MESSAGE, datetime(2026, 9, 21, 14, 13, 20, tzinfo=UTC)),
        (2, types.SESSION_MESSAGE, datetime(2026, 9, 21, 14, 14, 20, tzinfo=UTC)),
    ]
    assert (imported.provider, imported.provider_session_id, imported.model) == (
        "codex",
        THREAD_A,
        "gpt-5.5",
    )
    assert (imported.prompt, imported.cwd) == ("Fix the login bug please", setup.root)
    assert imported.history == [(e.type, e.payload) for e in events]


async def test_continuing_an_archived_codex_chat_restores_it_in_codex(setup: Setup) -> None:
    # Codex refuses to resume an archived thread, so the continued chat could not reply.
    setup.threads.add(THREAD_A, setup.root, archived=True)
    await setup.chats.list_chats()

    await setup.chats.importable(THREAD_A)

    assert setup.server.requests("thread/unarchive") == [{"threadId": THREAD_A}]
    assert [thread["id"] for thread in setup.threads.active] == [THREAD_A]


def test_a_recorded_turn_becomes_the_blocks_a_live_codex_run_makes() -> None:
    turn: dict[str, JsonValue] = {
        "id": "turn-1",
        "startedAt": 1790000000,
        "completedAt": 1790000060,
        "items": [
            {
                "type": "userMessage",
                "id": "u1",
                "content": [
                    {"type": "text", "text": "Run the tests"},
                    {"type": "localImage", "path": "shot.png"},
                ],
            },
            {"type": "reasoning", "id": "r1", "summary": ["Check the suite"], "content": []},
            {
                "type": "commandExecution",
                "id": "c1",
                "command": "/bin/zsh -lc 'make test'",
                "status": "completed",
                "exitCode": 1,
                "aggregatedOutput": "1 failed",
            },
            {
                "type": "fileChange",
                "id": "f1",
                "status": "completed",
                "changes": [
                    {"path": "a.py", "kind": {"type": "update"}, "diff": "@@ -1 +1 @@\n-x\n+y\n"}
                ],
            },
            {"type": "collabAgentToolCall", "id": "s1", "tool": "spawnAgent"},
            {"type": "agentMessage", "id": "a1", "text": "One test fails."},
        ],
    }

    history = thread_history([turn])

    assert [(item.type, item.payload) for item in history] == [
        (types.SESSION_USER_MESSAGE, {"text": "Run the tests\n[image]", "attachments": []}),
        (
            types.SESSION_MESSAGE,
            {
                "blocks": [{"type": "thinking", "text": "Check the suite", "duration_ms": None}],
                "parent_tool_use_id": None,
            },
        ),
        (
            types.SESSION_MESSAGE,
            {
                "blocks": [
                    {
                        "type": "tool_use",
                        "id": "c1",
                        "name": "Bash",
                        "input": {"command": "make test"},
                    }
                ],
                "parent_tool_use_id": None,
            },
        ),
        (
            types.SESSION_MESSAGE,
            {
                "blocks": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "c1",
                        "content": "1 failed",
                        "is_error": True,
                    }
                ],
                "parent_tool_use_id": None,
            },
        ),
        (
            types.SESSION_MESSAGE,
            {
                "blocks": [
                    {
                        "type": "tool_use",
                        "id": "f1",
                        "name": "Edit",
                        "input": {
                            "file_path": "a.py",
                            "old_string": "x",
                            "new_string": "y",
                            "diff": "@@ -1 +1 @@\n-x\n+y\n",
                        },
                    }
                ],
                "parent_tool_use_id": None,
            },
        ),
        (
            types.SESSION_MESSAGE,
            {
                "blocks": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "f1",
                        "content": "Done",
                        "is_error": False,
                    }
                ],
                "parent_tool_use_id": None,
            },
        ),
        (
            types.SESSION_MESSAGE,
            {"blocks": [{"type": "text", "text": "One test fails."}], "parent_tool_use_id": None},
        ),
    ]
