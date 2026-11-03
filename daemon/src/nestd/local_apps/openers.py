"""How each platform opens VS Code, the file manager and a terminal, run by an injectable
command runner. macOS goes through `open`; Linux runs the apps' own commands."""

import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, Protocol

from nestd.gitops.runner import CommandError, CommandRunner
from nestd.local_apps.errors import AppNotInstalledError, LocalAppError
from nestd.platform import Platform

type RepoApp = Literal["vscode", "finder", "terminal"]
type Which = Callable[[str], str | None]

# The app's name, and the `open` options that pick it.
_MAC_APPS: dict[RepoApp, tuple[str, tuple[str, ...]]] = {
    "vscode": ("Visual Studio Code", ("-a", "Visual Studio Code")),
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

    async def open_repo(self, path: Path, app: RepoApp) -> None: ...

    async def open_launcher(self, launcher: Path) -> None:
        """Run the launcher script in a new terminal window."""
        ...


def opener_for(platform: Platform, run: CommandRunner, cwd: Path, which: Which) -> Opener:
    match platform.name:
        case "macos":
            return MacOpener(run, cwd)
        case "linux":
            return LinuxOpener(run, cwd, which)


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
    def __init__(self, run: CommandRunner, cwd: Path) -> None:
        self._run = run
        self._cwd = cwd

    @property
    def launcher_suffix(self) -> str:
        """Terminal runs a `.command` file when it is opened, which needs no Automation
        permission."""
        return ".command"

    async def open_repo(self, path: Path, app: RepoApp) -> None:
        name, options = _MAC_APPS[app]
        await self._open(name, [*options, str(path)])

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
    def __init__(self, run: CommandRunner, cwd: Path, which: Which = shutil.which) -> None:
        self._run = run
        self._cwd = cwd
        self._which = which

    @property
    def launcher_suffix(self) -> str:
        return ".sh"

    async def open_repo(self, path: Path, app: RepoApp) -> None:
        match app:
            case "vscode":
                self._require("code", "Visual Studio Code")
                await _run(self._run, "Visual Studio Code", ["code", str(path)], self._cwd)
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
