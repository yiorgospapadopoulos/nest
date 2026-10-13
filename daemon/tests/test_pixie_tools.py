from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import JsonValue

from harness.paths import AppPaths
from harness.pixies.files import PixieFiles
from harness.pixies.models import Pixie
from harness.pixies.tools import TOOL_NAMES, pixie_tools
from harness.providers.base import AgentTool, ToolRefusedError
from harness.repos.service import RepoService
from tests.fakes import FakeClock
from tests.git_support import init_repo

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


def pixie(projects: list[str] | None = None) -> Pixie:
    return Pixie(
        id="p1",
        slug="tester",
        name="Tester",
        position=0,
        chat_session_id=None,
        created_at=NOW,
        updated_at=NOW,
        projects=projects,
    )


@pytest.fixture
def setup(tmp_path: Path) -> tuple[PixieFiles, RepoService]:
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    paths.ensure()
    files = PixieFiles(paths.pixies_dir)
    files.create("p1", "You test.")
    return files, RepoService(paths)


def by_name(tools: tuple[AgentTool, ...]) -> dict[str, AgentTool]:
    return {tool.name: tool for tool in tools}


async def call(tools: dict[str, AgentTool], tool: str, /, **args: JsonValue) -> str:
    return await tools[tool].handler(args)


async def test_memory_round_trip(setup: tuple[PixieFiles, RepoService]) -> None:
    files, repos = setup
    tools = by_name(pixie_tools(pixie(), files, repos, FakeClock(NOW)))

    saved = await call(tools, "memory_write", fact="prefers squash merges")
    memory = await call(tools, "memory_read")
    forgot = await call(tools, "memory_forget", text="squash")
    none_left = await call(tools, "memory_forget", text="squash")

    assert tuple(tools) == TOOL_NAMES
    assert saved == "Saved: - 2026-10-13: prefers squash merges"
    assert "- 2026-10-13: prefers squash merges" in memory
    assert forgot == "Forgot 1 fact."
    assert none_left == "No fact matched."


async def test_notes_and_search(setup: tuple[PixieFiles, RepoService]) -> None:
    files, repos = setup
    tools = by_name(pixie_tools(pixie(), files, repos, FakeClock(NOW)))

    await call(tools, "note_write", name="release", text="tag then build")
    await call(tools, "note_write", name="release", text="build then tag")
    note = await call(tools, "note_read", name="release")
    hits = await call(tools, "notes_search", query="TAG")
    nothing = await call(tools, "notes_search", query="zzz")

    assert note == "build then tag\n"
    assert hits == "notes/release.md: build then tag"
    assert nothing == "Nothing found."
    with pytest.raises(ToolRefusedError):
        await call(tools, "note_read", name="../SOUL")
    with pytest.raises(ToolRefusedError):
        await call(tools, "note_read", name="missing")


async def test_soul_and_projects(tmp_path: Path, setup: tuple[PixieFiles, RepoService]) -> None:
    files, repos = setup
    await repos.register(init_repo(tmp_path / "web"))
    await repos.register(init_repo(tmp_path / "api"))
    all_tools = by_name(pixie_tools(pixie(), files, repos, FakeClock(NOW)))
    some_tools = by_name(pixie_tools(pixie(["web"]), files, repos, FakeClock(NOW)))

    await call(all_tools, "soul_write", text="You review code.")
    soul = await call(all_tools, "soul_read")

    assert soul == "You review code.\n"
    assert await call(all_tools, "list_projects") == "api\nweb"
    assert await call(some_tools, "list_projects") == "web"


async def test_blank_forget_and_search_are_refused(setup: tuple[PixieFiles, RepoService]) -> None:
    files, repos = setup
    tools = by_name(pixie_tools(pixie(), files, repos, FakeClock(NOW)))
    await call(tools, "memory_write", fact="keep me")
    before = await call(tools, "memory_read")

    for text in ("", "   ", "\n\t"):
        with pytest.raises(ToolRefusedError, match=r"Say which fact to forget\."):
            await call(tools, "memory_forget", text=text)
    with pytest.raises(ToolRefusedError, match=r"Say which fact to forget\."):
        await call(tools, "memory_forget")
    with pytest.raises(ToolRefusedError, match=r"Say what to search for\."):
        await call(tools, "notes_search", query="  ")

    assert await call(tools, "memory_read") == before
