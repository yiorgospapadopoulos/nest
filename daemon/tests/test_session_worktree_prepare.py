"""Preparing a chat's worktree: links that cannot be made, and a nudge during setup (B34:
BUG-95, BUG-96).
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from nestd.config.models import WorktreeConfig
from nestd.events import types
from nestd.sessions.models import SessionState
from nestd.storage.db import Database
from nestd.worktrees.setup import link_files
from tests.async_support import until
from tests.fake_provider import reply
from tests.fakes import FakeClock
from tests.git_support import commit_file, git
from tests.session_support import Env


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    yield (environment := Env(tmp_path, db, clock))
    await environment.manager.shutdown()


def source_and_target(tmp_path: Path) -> tuple[Path, Path]:
    source, target = tmp_path / "source", tmp_path / "target"
    (source / "conf").mkdir(parents=True)
    (source / "conf" / "app.env").write_text("A=1", encoding="utf-8")
    (source / ".env").write_text("B=2", encoding="utf-8")
    target.mkdir()
    return source, target


def test_a_link_through_a_file_is_reported_and_the_rest_are_made(tmp_path: Path) -> None:
    """BUG-96: in the worktree `conf` is a file, so nothing can be linked under it."""
    source, target = source_and_target(tmp_path)
    (target / "conf").write_text("tracked", encoding="utf-8")

    result = link_files(["conf/app.env", ".env"], source, target)

    assert result.failed == ["conf/app.env"]
    assert result.linked == [".env"]
    assert (target / "conf").read_text(encoding="utf-8") == "tracked"
    assert (target / ".env").is_symlink()


def test_a_link_whose_folder_leads_out_of_the_worktree_is_refused(tmp_path: Path) -> None:
    """BUG-96: a folder in the worktree that is a symlink elsewhere gets no link in it."""
    source, target = source_and_target(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (target / "conf").symlink_to(outside)

    result = link_files(["conf/app.env"], source, target)

    assert result.failed == ["conf/app.env"]
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("link", [".git", ".git/hooks", ".git/info/exclude"])
def test_links_into_git_itself_are_refused(link: str) -> None:
    """BUG-96: in a worktree `.git` is a file that git owns."""
    with pytest.raises(ValidationError, match=r"inside the repository, outside \.git"):
        WorktreeConfig(link=[link])


def test_names_that_only_start_like_git_are_links_like_any_other() -> None:
    assert WorktreeConfig(link=[".github/x.env", ".gitignore.local"]).link == [
        ".github/x.env",
        ".gitignore.local",
    ]


async def test_a_link_that_cannot_be_made_does_not_stop_the_chat(env: Env) -> None:
    """BUG-96: `conf` is tracked as a file, while the main checkout has a folder there."""
    commit_file(env.repo_path, "conf", "tracked\n")
    git(env.repo_path, "rm", "-q", "--cached", "conf")
    (env.repo_path / "conf").unlink()
    (env.repo_path / "conf").mkdir()
    (env.repo_path / "conf" / "app.env").write_text("A=1", encoding="utf-8")
    await env.register(WorktreeConfig(link=["conf/app.env"]))
    env.provider.script(reply("ok"))

    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    workspace = next(
        e for e in await env.bus.session_events(created.id) if e.type == types.SESSION_WORKSPACE
    )
    assert workspace.payload["failed"] == ["conf/app.env"]
    assert workspace.payload["linked"] == []


async def test_a_nudge_during_setup_lets_it_finish_before_the_prompt(env: Env) -> None:
    """BUG-95: the prompt never reaches the agent in a worktree that missed its setup; the
    nudge's message follows it, as when it comes while the run opens (D036).
    """
    await env.register(
        WorktreeConfig(setup=["touch started; while [ ! -f go ]; do sleep 0.02; done; touch ran"])
    )
    env.provider.script(reply("on it"), reply("answer to the nudge"))
    created = await env.create()

    async def setting_up() -> bool:
        session = await env.store.get(created.id)
        return session.cwd is not None and (session.cwd / "started").exists()

    await until(setting_up)
    sent = await env.manager.send(created.id, "You seem stuck", [], interrupt=True)
    session = await env.store.get(created.id)
    assert session.cwd is not None
    (session.cwd / "go").touch()
    await until(lambda: bool(env.provider.runs) and len(env.provider.runs[0].inputs) == 2)
    await env.reach(created.id, SessionState.IDLE)

    assert sent.queued_message is not None
    assert (session.cwd / "ran").exists()
    assert [i.text for i in env.provider.runs[0].inputs] == [
        "Fix the bug\nDetails here",
        "You seem stuck",
    ]
    assert types.SESSION_SETUP_FAILED not in await env.event_types(created.id)
    assert "interrupted" not in await env.states(created.id)
