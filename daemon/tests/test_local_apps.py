import os
import shlex
from pathlib import Path

import pytest

from nestd.errors import ConflictError
from nestd.gitops.runner import CommandError
from nestd.local_apps.apps import LIVE_WARNING, LocalApps, RepoApp
from nestd.local_apps.errors import AppNotInstalledError, LocalAppError
from nestd.local_apps.launchers import launcher_script
from nestd.platform import LINUX, MACOS
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
    return LocalApps(opener, tmp_path / "launchers", MACOS)


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


# B117: Linux opens apps by their commands on the PATH.
DETACH = ("/bin/sh", "-c", '"$@" </dev/null >/dev/null 2>&1 &', "nest-open")


def linux_apps(opener: FakeOpener, tmp_path: Path, *installed: str) -> LocalApps:
    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in installed else None

    return LocalApps(opener, tmp_path / "launchers", LINUX, which=which)


async def test_linux_opens_vs_code_and_the_file_manager_by_their_commands(
    opener: FakeOpener, tmp_path: Path
) -> None:
    apps = linux_apps(opener, tmp_path, "code", "xdg-open")

    await apps.open_repo(tmp_path, "vscode")
    await apps.open_repo(tmp_path, "finder")

    assert opener.calls == [
        (("code", str(tmp_path)), tmp_path / "launchers"),
        (("xdg-open", str(tmp_path)), tmp_path / "launchers"),
    ]


@pytest.mark.parametrize(
    ("app", "message"),
    [
        ("vscode", "Visual Studio Code is not installed on this computer"),
        ("finder", "xdg-open is not installed on this computer"),
        ("terminal", "No terminal app is installed on this computer"),
    ],
)
async def test_linux_reports_a_missing_app_without_running_anything(
    opener: FakeOpener, tmp_path: Path, app: RepoApp, message: str
) -> None:
    apps = linux_apps(opener, tmp_path)

    with pytest.raises(AppNotInstalledError, match=message):
        await apps.open_repo(tmp_path, app)
    assert opener.calls == []


async def test_linux_opens_a_terminal_in_the_folder_without_waiting_for_it(
    opener: FakeOpener, tmp_path: Path
) -> None:
    """A terminal runs until it is closed, so it starts through a shell that exits at once;
    x-terminal-emulator (the system's choice) wins over gnome-terminal."""
    await linux_apps(opener, tmp_path, "x-terminal-emulator", "gnome-terminal").open_repo(
        tmp_path, "terminal"
    )
    await linux_apps(opener, tmp_path, "gnome-terminal").open_repo(tmp_path, "terminal")

    assert opener.calls == [
        ((*DETACH, "x-terminal-emulator"), tmp_path),
        ((*DETACH, "gnome-terminal", f"--working-directory={tmp_path}"), tmp_path),
    ]


async def test_linux_continues_a_conversation_in_a_terminal_running_a_shell_launcher(
    opener: FakeOpener, tmp_path: Path
) -> None:
    launch = await linux_apps(opener, tmp_path, "gnome-terminal").open_in_claude_code(
        session(tmp_path), live=False
    )
    await linux_apps(opener, tmp_path, "x-terminal-emulator").open_in_claude_code(
        session(tmp_path), live=False
    )

    assert launch.launcher == tmp_path / "launchers" / "abc123.sh"
    assert launch.launcher.read_text(encoding="utf-8") == launcher_script(tmp_path, "sdk-1")
    assert os.access(launch.launcher, os.X_OK)
    assert opener.calls == [
        ((*DETACH, "gnome-terminal", "--", str(launch.launcher)), tmp_path / "launchers"),
        ((*DETACH, "x-terminal-emulator", "-e", str(launch.launcher)), tmp_path / "launchers"),
    ]


async def test_linux_reports_a_failed_command(opener: FakeOpener, tmp_path: Path) -> None:
    opener.failure = CommandError(["code"], 1, "cannot open display\n")

    with pytest.raises(LocalAppError) as caught:
        await linux_apps(opener, tmp_path, "code").open_repo(tmp_path, "vscode")
    assert str(caught.value) == "could not open Visual Studio Code: cannot open display"
