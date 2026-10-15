"""B59: `!` runs a shell command for the next message, `#` adds a line to CLAUDE.md."""

import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from nestd.composer.memory import append_memory
from nestd.composer.service import ComposerActions, NoUserMemoryError
from nestd.composer.shell import context_block, run_command
from nestd.sessions.errors import NoWorkspaceError, PixieChatError, SessionNotFoundError
from nestd.sessions.models import Session
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.fakes import FakeClock
from tests.test_session_store import new_session

SHELL = "/bin/sh"


@pytest.fixture
def real_tmp(tmp_path: Path) -> Path:
    return tmp_path.resolve()


async def test_a_command_runs_in_the_folder_with_the_environment_given(real_tmp: Path) -> None:
    result = await run_command(
        'printf "%s %s\\n" "$(pwd -P)" "$NEST_TEST"; echo oops >&2; exit 3',
        real_tmp,
        {"PATH": os.environ["PATH"], "NEST_TEST": "from the profile"},
        SHELL,
    )

    assert result.command.startswith("printf")
    assert result.exit_code == 3
    assert result.output == f"{real_tmp} from the profile\noops\n"
    assert result.truncated is False
    assert result.timed_out is False


async def test_long_output_is_cut_and_marked(tmp_path: Path) -> None:
    result = await run_command(
        "i=0; while [ $i -lt 2000 ]; do echo 0123456789; i=$((i+1)); done",
        tmp_path,
        {"PATH": os.environ["PATH"]},
        SHELL,
        max_output=25,
    )

    assert result.exit_code == 0
    assert result.output == "0123456789\n0123456789\n012"
    assert result.truncated is True
    assert result.context.endswith(
        "012\n[output truncated]</bash-stdout><bash-stderr></bash-stderr>"
    )


async def test_a_command_that_runs_too_long_is_stopped_with_what_it_printed(
    tmp_path: Path,
) -> None:
    # The background child keeps the output open: it is stopped with the command.
    result = await run_command(
        "echo started; sleep 30 & sleep 30",
        tmp_path,
        {"PATH": os.environ["PATH"]},
        SHELL,
        seconds=0.5,
    )

    assert result.exit_code is None
    assert result.timed_out is True
    assert result.output == "started\n"
    assert "[timed out after 0.5 seconds]" in result.context


def test_the_context_is_the_block_claude_code_sends() -> None:
    assert context_block("ls", "a\nb\n", truncated=False, timed_out=None) == (
        "<bash-input>ls</bash-input>\n<bash-stdout>a\nb</bash-stdout><bash-stderr></bash-stderr>"
    )


async def test_a_memory_line_is_appended_and_the_file_created(tmp_path: Path) -> None:
    created = tmp_path / "new" / "CLAUDE.md"
    existing = tmp_path / "CLAUDE.md"
    existing.write_text("# Notes\n- old", encoding="utf-8")

    assert await append_memory(created, "Use uv") == created
    assert await append_memory(existing, "  Two\nlines  ") == existing
    assert await append_memory(existing, "Third") == existing

    assert created.read_text(encoding="utf-8") == "- Use uv\n"
    assert existing.read_text(encoding="utf-8") == "# Notes\n- old\n- Two lines\n- Third\n"


async def test_a_linked_memory_file_writes_its_target(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_text("# Agents\n", encoding="utf-8")
    link = tmp_path / "CLAUDE.md"
    link.symlink_to("AGENTS.md")

    written = await append_memory(link, "Run make check")

    assert written == target.resolve()
    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "# Agents\n- Run make check\n"


async def fixed_env() -> Mapping[str, str]:
    return {"NEST_TEST": "profile"}


@pytest.fixture
def store(db: Database, clock: FakeClock) -> SessionStore:
    return SessionStore(db, clock)


def actions(
    store: SessionStore, tmp_path: Path, user_memory: Path | None, **changes: object
) -> ComposerActions:
    """`changes` alter every session looked up, such as a pixie's id (a real one would need
    a pixie row).
    """

    async def get(session_id: str) -> Session:
        return (await store.get(session_id)).model_copy(update=changes)

    return ComposerActions(
        sessions=get,
        project_folder=lambda repo: tmp_path / "projects" / repo,
        user_memory=user_memory,
        shell_env=fixed_env,
        shell=SHELL,
        base_env={"PATH": os.environ["PATH"], "NEST_TEST": "daemon", "PWD": "/elsewhere"},
    )


async def test_a_chats_command_runs_in_its_folder_with_the_login_shell_env(
    store: SessionStore, tmp_path: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    session = await store.create(new_session(cwd=worktree))

    result = await actions(store, tmp_path, None).run_shell(session.id, 'echo "$NEST_TEST $PWD"')

    assert result.output == f"profile {worktree}\n"
    assert result.exit_code == 0


async def test_pixie_chats_and_the_chats_pixies_start_cannot_run_commands(
    store: SessionStore, tmp_path: Path
) -> None:
    session = await store.create(new_session(cwd=tmp_path))

    for changes in ({"pixie_id": "p1"}, {"started_by_pixie": "p1"}):
        composer = actions(store, tmp_path, None, **changes)
        with pytest.raises(PixieChatError, match="pixie's chat cannot run shell commands"):
            await composer.run_shell(session.id, "ls")


async def test_commands_need_the_chats_folder(store: SessionStore, tmp_path: Path) -> None:
    gone = await store.create(new_session(cwd=tmp_path / "gone"))
    composer = actions(store, tmp_path, None)

    with pytest.raises(NoWorkspaceError):
        await composer.run_shell(gone.id, "ls")
    with pytest.raises(SessionNotFoundError):
        await composer.run_shell("nope", "ls")


async def test_project_memory_goes_to_the_projects_folder_and_user_memory_to_claudes(
    store: SessionStore, tmp_path: Path
) -> None:
    session = await store.create(new_session(repo="app", cwd=tmp_path / "worktree"))
    user_memory = tmp_path / "claude" / "CLAUDE.md"
    composer = actions(store, tmp_path, user_memory)

    project = await composer.remember(session.id, "Use uv", "project")
    user = await composer.remember(session.id, "Answer briefly", "user")

    assert project.path == tmp_path / "projects" / "app" / "CLAUDE.md"
    assert project.scope == "project"
    assert project.line == "- Use uv"
    assert project.path.read_text(encoding="utf-8") == "- Use uv\n"
    assert user.path == user_memory
    assert user_memory.read_text(encoding="utf-8") == "- Answer briefly\n"


async def test_a_pixie_chat_has_only_user_memory(store: SessionStore, tmp_path: Path) -> None:
    session = await store.create(new_session(repo="pixie:p1", cwd=tmp_path))
    composer = actions(store, tmp_path, tmp_path / "CLAUDE.md", pixie_id="p1")

    with pytest.raises(PixieChatError, match="no project memory"):
        await composer.remember(session.id, "x", "project")
    assert (await composer.remember(session.id, "x", "user")).path == tmp_path / "CLAUDE.md"


async def test_user_memory_needs_claudes_folder(store: SessionStore, tmp_path: Path) -> None:
    session = await store.create(new_session(cwd=tmp_path))

    with pytest.raises(NoUserMemoryError, match="Claude Code's config folder"):
        await actions(store, tmp_path, None).remember(session.id, "x", "user")
