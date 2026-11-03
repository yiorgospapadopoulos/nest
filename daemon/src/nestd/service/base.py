"""What every platform's background service shares: running its manager's commands and
the install, uninstall and status the `nestd service` commands call."""

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ServiceError(Exception):
    """A service manager command failed."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


type CommandRunner = Callable[[Sequence[str]], CommandResult]


def run_command(args: Sequence[str]) -> CommandResult:
    completed = subprocess.run(args, capture_output=True, text=True, check=False)  # noqa: S603
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class ServiceStatus:
    installed: bool
    loaded: bool
    detail: str


class ServiceManager(Protocol):
    @property
    def unit_path(self) -> Path:
        """The file that defines the service."""
        ...

    def install(self) -> None:
        """Write the service file and start it. Reinstalling replaces a running service."""
        ...

    def remove_legacy(self) -> bool:
        """Stop and remove the service from before the rename to Nest (B43); whether one
        was there."""
        ...

    def uninstall(self) -> None: ...

    def status(self) -> ServiceStatus: ...
