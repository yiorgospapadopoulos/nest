"""How each platform finds the installed editors and opens a project in one of them, the
file manager or a terminal, run by an injectable command runner. macOS goes through `open`;
Linux runs the apps' own commands."""

import os
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, Protocol

from nestd.gitops.runner import CommandError, CommandRunner
from nestd.local_apps.editors import EDITORS, EDITORS_BY_ID, Editor, EditorId
from nestd.local_apps.errors import AppNotInstalledError, LocalAppError
from nestd.platform import Platform

type RepoApp = EditorId | Literal["finder", "terminal"]
type Which = Callable[[str], str | None]

# The app's name, and the `open` options that pick it.
_MAC_TOOLS: dict[Literal["finder", "terminal"], tuple[str, tuple[str, ...]]] = {
    "finder": ("Finder", ()),
    "terminal": ("Terminal", ("-a", "Terminal")),
}
# What `open -a` prints when the app is not installed.
_NOT_INSTALLED = "Unable to find application"
# The system's chosen terminal on Debian and Ubuntu first, then GNOME's.
_LINUX_TERMINALS = ("x-terminal-emulator", "gnome-terminal")
# A terminal runs until it is closed: started through a shell that exits at once, so the
# request waits for nothing.
_DETACHED = ("/bin/sh", "-c", '"$@" </dev/null >/dev/null 2>&1 &', "nest-open")


class Opener(Protocol):
    @property
    def launcher_suffix(self) -> str: ...

    def installed_editors(self) -> list[Editor]:
        """The editors found on this computer, in the order of `EDITORS`. Reads folders."""
        ...

    async def open_repo(self, path: Path, app: RepoApp) -> None: ...

    async def open_launcher(self, launcher: Path) -> None:
        """Run the launcher script in a new terminal window."""
        ...


def opener_for(
    platform: Platform,
    run: CommandRunner,
    cwd: Path,
    which: Which,
    search: Sequence[Path] | None = None,
) -> Opener:
    """`search` replaces the folders looked in for editors (tests); see `editor_folders`."""
    folders = editor_folders(platform, Path.home()) if search is None else tuple(search)
    match platform.name:
        case "macos":
            return MacOpener(run, cwd, folders)
        case "linux":
            return LinuxOpener(run, cwd, which, folders)


def editor_folders(platform: Platform, home: Path) -> tuple[Path, ...]:
    """Where editors are looked for. macOS: the app folders, JetBrains Toolbox's old one
    included. Linux, after the PATH, which the background service keeps short: JetBrains
    Toolbox's launchers, snaps and flatpaks."""
    match platform.name:
        case "macos":
            apps = home / "Applications"
            return (Path("/Applications"), apps, apps / "JetBrains Toolbox")
        case "linux":
            share = home / ".local" / "share"
            return (
                share / "JetBrains" / "Toolbox" / "scripts",
                Path("/snap/bin"),
                share / "flatpak" / "exports" / "bin",
                Path("/var/lib/flatpak/exports/bin"),
            )


async def _run(run: CommandRunner, app_name: str, argv: Sequence[str], cwd: Path) -> None:
    try:
        await run(argv, cwd)
    except CommandError as error:
        msg = f"could not open {app_name}: {error.stderr.strip()}"
        raise LocalAppError(msg) from error
    except OSError as error:
        msg = f"could not open {app_name}: {error}"
        raise LocalAppError(msg) from error


class MacOpener:
    def __init__(self, run: CommandRunner, cwd: Path, app_folders: Sequence[Path]) -> None:
        self._run = run
        self._cwd = cwd
        self._app_folders = tuple(app_folders)

    @property
    def launcher_suffix(self) -> str:
        """Terminal runs a `.command` file when it is opened, which needs no Automation
        permission."""
        return ".command"

    def installed_editors(self) -> list[Editor]:
        return [editor for editor in EDITORS if self._app(editor) is not None]

    async def open_repo(self, path: Path, app: RepoApp) -> None:
        if app == "finder" or app == "terminal":
            name, options = _MAC_TOOLS[app]
            await self._open(name, [*options, str(path)])
            return
        editor = EDITORS_BY_ID[app]
        # An app outside the usual folders is still found by its name.
        bundle = self._app(editor) or editor.mac_apps[0]
        await self._open(editor.name, ["-a", bundle.removesuffix(".app"), str(path)])

    def _app(self, editor: Editor) -> str | None:
        """The editor's app bundle found in the app folders, if any."""
        for bundle in editor.mac_apps:
            if any((folder / bundle).is_dir() for folder in self._app_folders):
                return bundle
        return None

    async def open_launcher(self, launcher: Path) -> None:
        await self._open("Terminal", [str(launcher)])

    async def _open(self, app_name: str, args: Sequence[str]) -> None:
        try:
            await self._run(["open", *args], self._cwd)
        except CommandError as error:
            if _NOT_INSTALLED in error.stderr:
                msg = f"{app_name} is not installed on this Mac"
                raise AppNotInstalledError(msg) from error
            msg = f"could not open {app_name}: {error.stderr.strip()}"
            raise LocalAppError(msg) from error
        except OSError as error:
            msg = f"could not open {app_name}: {error}"
            raise LocalAppError(msg) from error


class LinuxOpener:
    def __init__(
        self,
        run: CommandRunner,
        cwd: Path,
        which: Which = shutil.which,
        launcher_folders: Sequence[Path] = (),
    ) -> None:
        self._run = run
        self._cwd = cwd
        self._which = which
        self._launcher_folders = tuple(launcher_folders)

    @property
    def launcher_suffix(self) -> str:
        return ".sh"

    def installed_editors(self) -> list[Editor]:
        return [editor for editor in EDITORS if self._launcher(editor) is not None]

    async def open_repo(self, path: Path, app: RepoApp) -> None:
        match app:
            case "finder":
                self._require("xdg-open", "xdg-open")
                await _run(self._run, "the file manager", ["xdg-open", str(path)], self._cwd)
            case "terminal":
                terminal = self._terminal()
                argv = [terminal]
                if terminal == "gnome-terminal":
                    # Its windows belong to a server that does not start in our folder.
                    argv.append(f"--working-directory={path}")
                await _run(self._run, terminal, [*_DETACHED, *argv], path)
            case _:
                editor = EDITORS_BY_ID[app]
                launcher = self._launcher(editor)
                if launcher is None:
                    msg = f"{editor.name} is not installed on this computer"
                    raise AppNotInstalledError(msg)
                # Detached like a terminal: a JetBrains launcher runs as long as the IDE.
                await _run(self._run, editor.name, [*_DETACHED, launcher, str(path)], path)

    def _launcher(self, editor: Editor) -> str | None:
        """The editor's command on the PATH, else in the launcher folders."""
        for command in editor.linux_commands:
            found = self._which(command)
            if found is not None:
                return found
            for folder in self._launcher_folders:
                candidate = folder / command
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate)
        return None

    async def open_launcher(self, launcher: Path) -> None:
        terminal = self._terminal()
        run_flag = "--" if terminal == "gnome-terminal" else "-e"
        argv = [*_DETACHED, terminal, run_flag, str(launcher)]
        await _run(self._run, terminal, argv, self._cwd)

    def _require(self, command: str, app_name: str) -> None:
        if self._which(command) is None:
            msg = f"{app_name} is not installed on this computer"
            raise AppNotInstalledError(msg)

    def _terminal(self) -> str:
        for terminal in _LINUX_TERMINALS:
            if self._which(terminal) is not None:
                return terminal
        msg = (
            "No terminal app is installed on this computer: Nest looks for "
            "x-terminal-emulator, then gnome-terminal"
        )
        raise AppNotInstalledError(msg)
