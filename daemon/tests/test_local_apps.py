import os
import shlex
import subprocess
from pathlib import Path

import pytest

from nestd.errors import ConflictError
from nestd.gitops.runner import CommandError
from nestd.local_apps.apps import LIVE_WARNING, LocalApps, RepoApp
from nestd.local_apps.editors import EDITORS, EditorId
from nestd.local_apps.errors import AppNotInstalledError, LocalAppError
from nestd.local_apps.launchers import (
    SIGN_IN_MARKER,
    launcher_script,
    limit_reset_script,
    write_sign_in_launcher,
)
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
    return LocalApps(opener, tmp_path / "launchers", MACOS, editor_folders=[tmp_path / "apps"])


def install_mac_apps(tmp_path: Path, *bundles: str) -> None:
    for bundle in bundles:
        (tmp_path / "apps" / bundle / "Contents").mkdir(parents=True)


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
        ("cursor", ("open", "-a", "Cursor")),
        ("xcode", ("open", "-a", "Xcode")),
        ("pycharm", ("open", "-a", "PyCharm")),
        ("finder", ("open",)),
        ("terminal", ("open", "-a", "Terminal")),
    ],
)
async def test_open_repo(
    apps: LocalApps, opener: FakeOpener, tmp_path: Path, app: RepoApp, args: tuple[str, ...]
) -> None:
    await apps.open_repo(tmp_path, app, None)

    assert opener.calls == [((*args, str(tmp_path)), tmp_path / "launchers")]


# B152: editors are listed only when installed, and the shortcut opens the default one.
async def test_mac_lists_the_installed_editors_in_open_in_order(
    apps: LocalApps, tmp_path: Path
) -> None:
    install_mac_apps(tmp_path, "PyCharm CE.app", "Zed.app", "Visual Studio Code.app")
    (tmp_path / "apps" / "Cursor.app").parent.mkdir(exist_ok=True)
    (tmp_path / "apps" / "Cursor.app").write_text("not an app bundle")

    installed = await apps.installed_editors()

    assert [editor.id for editor in installed] == ["vscode", "zed", "pycharm"]


async def test_mac_opens_the_bundle_it_found(
    apps: LocalApps, opener: FakeOpener, tmp_path: Path
) -> None:
    """A community edition has its own app name, which `open -a` needs."""
    install_mac_apps(tmp_path, "PyCharm CE.app")

    await apps.open_repo(tmp_path, "pycharm", None)

    assert opener.calls == [(("open", "-a", "PyCharm CE", str(tmp_path)), tmp_path / "launchers")]


@pytest.mark.parametrize(
    ("chosen", "opened"),
    [("zed", "Zed"), (None, "Visual Studio Code"), ("cursor", "Visual Studio Code")],
)
async def test_the_editor_target_opens_the_default_editor(
    apps: LocalApps, opener: FakeOpener, tmp_path: Path, chosen: EditorId | None, opened: str
) -> None:
    """The chosen editor while it is installed, else the first installed one."""
    install_mac_apps(tmp_path, "Zed.app", "Visual Studio Code.app")

    await apps.open_repo(tmp_path, "editor", chosen)

    assert opener.calls == [(("open", "-a", opened, str(tmp_path)), tmp_path / "launchers")]


async def test_the_editor_target_with_no_editor_installed_runs_nothing(
    apps: LocalApps, opener: FakeOpener, tmp_path: Path
) -> None:
    with pytest.raises(AppNotInstalledError, match="No code editor is installed"):
        await apps.open_repo(tmp_path, "editor", "vscode")
    assert opener.calls == []


async def test_a_missing_app_is_reported(
    apps: LocalApps, opener: FakeOpener, tmp_path: Path
) -> None:
    opener.failure = CommandError(
        ["open"], 1, "Unable to find application named 'Visual Studio Code'\n"
    )

    with pytest.raises(AppNotInstalledError, match="VS Code is not installed") as caught:
        await apps.open_repo(tmp_path, "vscode", None)
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
        await apps.open_repo(tmp_path, "finder", None)
    assert str(caught.value) == f"could not open Finder: {message}"
    assert caught.value.status_code == 502


# B117: Linux opens apps by their commands on the PATH.
DETACH = ("/bin/sh", "-c", '"$@" </dev/null >/dev/null 2>&1 &', "nest-open")


def linux_apps(opener: FakeOpener, tmp_path: Path, *installed: str) -> LocalApps:
    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in installed else None

    folders = [tmp_path / "toolbox", tmp_path / "flatpak"]
    return LocalApps(opener, tmp_path / "launchers", LINUX, which=which, editor_folders=folders)


def install_launcher(folder: Path, name: str, executable: bool = True) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    launcher = folder / name
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755 if executable else 0o644)
    return launcher


async def test_linux_opens_editors_detached_and_the_file_manager_by_their_commands(
    opener: FakeOpener, tmp_path: Path
) -> None:
    """A JetBrains launcher runs as long as the IDE, so editors start detached."""
    apps = linux_apps(opener, tmp_path, "code", "xdg-open")

    await apps.open_repo(tmp_path, "vscode", None)
    await apps.open_repo(tmp_path, "finder", None)

    assert opener.calls == [
        ((*DETACH, "/usr/bin/code", str(tmp_path)), tmp_path),
        (("xdg-open", str(tmp_path)), tmp_path / "launchers"),
    ]


async def test_linux_finds_editors_off_the_path(opener: FakeOpener, tmp_path: Path) -> None:
    """The service's PATH is short: Toolbox launchers and flatpaks are looked for too, and
    a file that cannot run does not count."""
    install_launcher(tmp_path / "toolbox", "pycharm")
    zed = install_launcher(tmp_path / "flatpak", "dev.zed.Zed")
    install_launcher(tmp_path / "toolbox", "goland", executable=False)
    apps = linux_apps(opener, tmp_path, "cursor")

    installed = await apps.installed_editors()
    await apps.open_repo(tmp_path, "zed", None)

    assert [editor.id for editor in installed] == ["cursor", "zed", "pycharm"]
    assert opener.calls == [((*DETACH, str(zed), str(tmp_path)), tmp_path)]


def test_xcode_is_never_offered_on_linux() -> None:
    xcode = next(editor for editor in EDITORS if editor.id == "xcode")

    assert xcode.linux_commands == ()


@pytest.mark.parametrize(
    ("app", "message"),
    [
        ("vscode", "VS Code is not installed on this computer"),
        ("rider", "Rider is not installed on this computer"),
        ("finder", "xdg-open is not installed on this computer"),
        ("terminal", "No terminal app is installed on this computer"),
    ],
)
async def test_linux_reports_a_missing_app_without_running_anything(
    opener: FakeOpener, tmp_path: Path, app: RepoApp, message: str
) -> None:
    apps = linux_apps(opener, tmp_path)

    with pytest.raises(AppNotInstalledError, match=message):
        await apps.open_repo(tmp_path, app, None)
    assert opener.calls == []


async def test_linux_opens_a_terminal_in_the_folder_without_waiting_for_it(
    opener: FakeOpener, tmp_path: Path
) -> None:
    """A terminal runs until it is closed, so it starts through a shell that exits at once;
    x-terminal-emulator (the system's choice) wins over gnome-terminal."""
    await linux_apps(opener, tmp_path, "x-terminal-emulator", "gnome-terminal").open_repo(
        tmp_path, "terminal", None
    )
    await linux_apps(opener, tmp_path, "gnome-terminal").open_repo(tmp_path, "terminal", None)

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
    opener.failure = CommandError(["xdg-open"], 1, "cannot open display\n")

    with pytest.raises(LocalAppError) as caught:
        await linux_apps(opener, tmp_path, "xdg-open").open_repo(tmp_path, "finder", None)
    assert str(caught.value) == "could not open the file manager: cannot open display"


def test_the_limit_reset_launcher_quotes_the_profile_and_runs_only_claude_code() -> None:
    """B161: an added account's profile path reaches the shell quoted, and the script
    runs nothing but Claude Code's own `/limit-reset`.
    """
    profile = "/data/it's here; rm -rf ~"
    folder = Path("/data/limit reset")
    script = limit_reset_script(folder, {"CLAUDE_CONFIG_DIR": profile})

    assert script.startswith("#!/bin/sh\n")
    command = script.splitlines()[-1]
    assert shlex.split(command) == [
        "cd",
        str(folder),
        "&&",
        "exec",
        "env",
        f"CLAUDE_CONFIG_DIR={profile}",
        "claude",
        "/limit-reset",
    ]
    first = limit_reset_script(Path("/data"), {}).splitlines()[-1]
    assert first == "cd /data && exec claude /limit-reset"
    with pytest.raises(ValueError, match="not an environment variable name"):
        limit_reset_script(folder, {"X; rm -rf ~": "1"})


def fake_claude(tmp_path: Path) -> tuple[Path, Path]:
    """A `claude` that writes each run's account folder and arguments to a log."""
    log = tmp_path / "runs.log"
    program = tmp_path / "bin dir" / "claude"
    program.parent.mkdir()
    program.write_text(
        f'#!/bin/sh\necho "$CLAUDE_CONFIG_DIR $*" >> {shlex.quote(str(log))}\n', "utf-8"
    )
    program.chmod(0o755)
    return program, log


def run_launcher(launcher: Path) -> None:
    subprocess.run(["/bin/sh", str(launcher)], check=True, timeout=10)  # noqa: S603


def test_an_added_accounts_sign_in_runs_claude_codes_login_and_keeps_it(tmp_path: Path) -> None:
    """B162: the terminal runs Claude Code's own login on the account's folder; while Nest
    has the account, the login stays.
    """
    program, log = fake_claude(tmp_path)
    profile = tmp_path / "profiles" / "claude" / "abc123def456"
    launcher = tmp_path / "launchers" / "sign-in-abc123def456.command"

    write_sign_in_launcher(launcher, program, {"CLAUDE_CONFIG_DIR": str(profile)}, profile)
    run_launcher(launcher)

    assert (profile / SIGN_IN_MARKER).exists()
    assert log.read_text("utf-8").splitlines() == [f"{profile} auth login"]


def test_a_login_finished_after_nest_removed_the_account_is_signed_out_again(
    tmp_path: Path,
) -> None:
    """B162 security re-check: a cancelled or timed-out added account's folder is deleted,
    but the terminal's login goes on. Finished later, Claude Code would keep a login Nest
    never shows, so the script signs it out again.
    """
    program, log = fake_claude(tmp_path)
    profile = tmp_path / "profiles" / "claude" / "abc123def456"
    launcher = tmp_path / "launchers" / "sign-in-abc123def456.command"
    write_sign_in_launcher(launcher, program, {"CLAUDE_CONFIG_DIR": str(profile)}, profile)

    (profile / SIGN_IN_MARKER).unlink()
    profile.rmdir()
    run_launcher(launcher)

    assert log.read_text("utf-8").splitlines() == [
        f"{profile} auth login",
        f"{profile} auth logout",
    ]


def test_the_first_accounts_sign_in_is_never_signed_out_by_nest(tmp_path: Path) -> None:
    program, log = fake_claude(tmp_path)
    launcher = tmp_path / "launchers" / "sign-in-claude-main.command"

    write_sign_in_launcher(launcher, program, {}, None)
    run_launcher(launcher)

    assert log.read_text("utf-8").splitlines() == [" auth login"]
