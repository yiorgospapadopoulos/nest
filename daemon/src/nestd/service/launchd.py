"""Install, remove and inspect the daemon's launchd user agent."""

import plistlib
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from nestd.paths import CONFIG_DIR_ENV, DATA_DIR_ENV, AppPaths

LABEL = "com.nest.daemon"
# The service before the rename to Nest (B43), removed when the new one is installed.
LEGACY_LABEL = "com.harness.daemon"
LAUNCHCTL = "/bin/launchctl"
SYSTEM_PATH = ("/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")


class ServiceError(Exception):
    """A launchctl command failed."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


type CommandRunner = Callable[[Sequence[str]], CommandResult]


def run_command(args: Sequence[str]) -> CommandResult:
    completed = subprocess.run(args, capture_output=True, text=True, check=False)  # noqa: S603
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def build_path_env(home: Path) -> str:
    """PATH for the service so `claude`, `git`, `gh` and `uv` resolve as in a login shell."""
    return ":".join((str(home / ".local" / "bin"), "/opt/homebrew/bin", *SYSTEM_PATH))


def render_plist(program_args: Sequence[str], paths: AppPaths, path_env: str) -> str:
    log_file = str(paths.logs_dir / "daemon.log")
    plist = {
        "Label": LABEL,
        "ProgramArguments": list(program_args),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": log_file,
        "StandardErrorPath": log_file,
        "EnvironmentVariables": {
            "PATH": path_env,
            CONFIG_DIR_ENV: str(paths.config_dir),
            DATA_DIR_ENV: str(paths.data_dir),
        },
    }
    return plistlib.dumps(plist).decode()


@dataclass(frozen=True)
class ServiceStatus:
    installed: bool
    loaded: bool
    detail: str


@dataclass(frozen=True)
class LaunchdService:
    paths: AppPaths
    launch_agents_dir: Path
    uid: int
    runner: CommandRunner
    program_args: Sequence[str]
    path_env: str

    @property
    def plist_path(self) -> Path:
        return self.launch_agents_dir / f"{LABEL}.plist"

    @property
    def _domain(self) -> str:
        return f"gui/{self.uid}"

    @property
    def _target(self) -> str:
        return f"{self._domain}/{LABEL}"

    def install(self) -> None:
        """Write the plist and (re)load it. Reinstalling replaces a running service."""
        self.paths.ensure()
        self.launch_agents_dir.mkdir(parents=True, exist_ok=True)
        # Unload any previous version first; failure just means it was not loaded.
        self.runner([LAUNCHCTL, "bootout", self._target])
        plist = render_plist(self.program_args, self.paths, self.path_env)
        self.plist_path.write_text(plist, encoding="utf-8")
        result = self.runner([LAUNCHCTL, "bootstrap", self._domain, str(self.plist_path)])
        if result.returncode != 0:
            msg = f"launchctl bootstrap failed: {result.stderr.strip()}"
            raise ServiceError(msg)

    def remove_legacy(self) -> bool:
        """Stop the service from before the rename and remove its plist; whether one was
        there. A failed bootout just means it was not loaded."""
        self.runner([LAUNCHCTL, "bootout", f"{self._domain}/{LEGACY_LABEL}"])
        legacy = self.launch_agents_dir / f"{LEGACY_LABEL}.plist"
        if not legacy.exists():
            return False
        legacy.unlink()
        return True

    def uninstall(self) -> None:
        self.runner([LAUNCHCTL, "bootout", self._target])
        self.plist_path.unlink(missing_ok=True)

    def status(self) -> ServiceStatus:
        result = self.runner([LAUNCHCTL, "print", self._target])
        return ServiceStatus(
            installed=self.plist_path.exists(),
            loaded=result.returncode == 0,
            detail=result.stdout if result.returncode == 0 else result.stderr,
        )
