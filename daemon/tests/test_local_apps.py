import os
import shlex
from pathlib import Path

import pytest

from nestd.errors import ConflictError
from nestd.gitops.runner import CommandError
from nestd.local_apps.apps import LIVE_WARNING, LocalApps, RepoApp
from nestd.local_apps.errors import AppNotInstalledError, LocalAppError
from nestd.local_apps.launchers import launcher_script
from nestd.sessions.errors import NoWorkspaceError
from nestd.sessions.models import Session, SessionState
from tests.fake_opener import FakeOpener
from tests.fakes import START
from tests.test_session_store import new_session


def session(cwd: Path | None, provider_session_id: str | None = "sdk-1") -> Session:
    return Session(
        **new_session(cwd=cwd).model_dump(),
        id="abc123",
        state=SessionState.IDLE,
        worktree_path=None,
        branch=None,
        provider_session_id=provider_session_id,
        created_at=START,
        updated_at=START,
        last_error=None,
    )


@pytest.fixture
def opener() -> FakeOpener:
    return FakeOpener()


@pytest.fixture
def apps(opener: FakeOpener, tmp_path: Path) -> LocalApps:
    return LocalApps(opener, tmp_path / "launchers")


def test_the_launcher_quotes_the_folder_and_the_conversation() -> None:
    folder = "/work/it's here; rm -rf ~"
    script = launcher_script(Path(folder), "sdk-1 $(x)")

    assert script.startswith("#!/bin/sh\n")
    command = script.splitlines()[-1]
    assert command == (
        f"cd {shlex.quote(folder)} && exec claude --resume {shlex.quote('sdk-1 $(x)')}"
    )
    assert shlex.split(command)[:5] == ["cd", folder, "&&", "exec", "claude"]


async def test_open_in_claude_code_writes_and_opens_a_launcher(
    apps: LocalApps, opener: FakeOpener, tmp_path: Path
) -> None:
    launch = await apps.open_in_claude_code(session(tmp_path), live=False)

    assert launch.launcher == tmp_path / "launchers" / "abc123.command"
    assert launch.warning is None
    assert launch.launcher.read_text(encoding="utf-8") == launcher_script(tmp_path, "sdk-1")
    assert os.access(launch.launcher, os.X_OK)
    assert opener.calls == [(("open", str(launch.launcher)), tmp_path / "launchers")]


async def test_open_in_claude_code_warns_while_nest_runs_the_session(
    apps: LocalApps, tmp_path: Path
) -> None:
    launch = await apps.open_in_claude_code(session(tmp_path), live=True)

    assert launch.warning == LIVE_WARNING


async def test_open_in_claude_code_needs_a_conversation_and_a_folder(
    apps: LocalApps, opener: FakeOpener, tmp_path: Path
) -> None:
    with pytest.raises(ConflictError, match="no Claude Code conversation"):
        await apps.open_in_claude_code(session(tmp_path, provider_session_id=None), live=False)
    with pytest.raises(NoWorkspaceError):
        await apps.open_in_claude_code(session(None), live=False)
    with pytest.raises(NoWorkspaceError, match="no longer exists"):
        await apps.open_in_claude_code(session(tmp_path / "gone"), live=False)
    assert opener.calls == []


@pytest.mark.parametrize(
    ("app", "args"),
    [
        ("vscode", ("open", "-a", "Visual Studio Code")),
        ("finder", ("open",)),
        ("terminal", ("open", "-a", "Terminal")),
    ],
)
async def test_open_repo(
    apps: LocalApps, opener: FakeOpener, tmp_path: Path, app: RepoApp, args: tuple[str, ...]
) -> None:
    await apps.open_repo(tmp_path, app)

    assert opener.calls == [((*args, str(tmp_path)), tmp_path / "launchers")]


async def test_a_missing_app_is_reported(
    apps: LocalApps, opener: FakeOpener, tmp_path: Path
) -> None:
    opener.failure = CommandError(
        ["open"], 1, "Unable to find application named 'Visual Studio Code'\n"
    )

    with pytest.raises(AppNotInstalledError, match="Visual Studio Code is not installed") as caught:
        await apps.open_repo(tmp_path, "vscode")
    assert caught.value.status_code == 424


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (CommandError(["open"], 1, "The file /x does not exist.\n"), "The file /x does not exist."),
        (FileNotFoundError("No such file: 'open'"), "No such file: 'open'"),
    ],
)
async def test_other_open_failures(
    apps: LocalApps, opener: FakeOpener, tmp_path: Path, failure: Exception, message: str
) -> None:
    opener.failure = failure

    with pytest.raises(LocalAppError) as caught:
        await apps.open_repo(tmp_path, "finder")
    assert str(caught.value) == f"could not open Finder: {message}"
    assert caught.value.status_code == 502
