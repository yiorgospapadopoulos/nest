"""Install, remove and inspect the daemon's systemd user service (Linux)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from nestd.paths import CONFIG_DIR_ENV, DATA_DIR_ENV, AppPaths
from nestd.service.base import CommandResult, CommandRunner, ServiceError, ServiceStatus

UNIT_NAME = "nest.service"
SYSTEMCTL = ("systemctl", "--user")


def _escape(value: str) -> str:
    """`%` starts a systemd specifier; a line break would start a new setting."""
    if "\n" in value or "\r" in value:
        msg = f"cannot write a value with a line break into the service: {value!r}"
        raise ServiceError(msg)
    return value.replace("%", "%%")


def _quoted(value: str, *, command: bool = False) -> str:
    escaped = _escape(value).replace("\\", "\\\\").replace('"', '\\"')
    # Only command lines expand `$VARIABLE`.
    return f'"{escaped.replace("$", "$$") if command else escaped}"'


def render_unit(
    program_args: Sequence[str],
    paths: AppPaths,
    path_env: str,
    extra_env: Mapping[str, str] = MappingProxyType({}),
) -> str:
    log_file = _escape(str(paths.logs_dir / "daemon.log"))
    environment = {
        "PATH": path_env,
        CONFIG_DIR_ENV: str(paths.config_dir),
        DATA_DIR_ENV: str(paths.data_dir),
        **extra_env,
    }
    lines = [
        "[Unit]",
        "Description=Nest daemon",
        "",
        "[Service]",
        "ExecStart=" + " ".join(_quoted(arg, command=True) for arg in program_args),
        # Also after a clean exit: the restart route ends the daemon with SIGTERM.
        "Restart=always",
        # Slow enough that a daemon failing at start (a locked keyring) never reaches
        # systemd's start limit, so it comes back once the cause is fixed.
        "RestartSec=5",
        # Only the daemon stops with the service: the terminals, editors and model servers
        # it opened for the user keep running, as they do on macOS. The daemon ends its own
        # agents when it stops.
        "KillMode=process",
        *(f"Environment={_quoted(f'{name}={value}')}" for name, value in environment.items()),
        f"StandardOutput=append:{log_file}",
        f"StandardError=append:{log_file}",
        "",
        "[Install]",
        "WantedBy=default.target",
    ]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class SystemdService:
    paths: AppPaths
    # ~/.config/systemd/user, or under $XDG_CONFIG_HOME.
    unit_dir: Path
    runner: CommandRunner
    program_args: Sequence[str]
    path_env: str
    extra_env: Mapping[str, str] = field(default_factory=dict[str, str])

    @property
    def unit_path(self) -> Path:
        return self.unit_dir / UNIT_NAME

    def install(self) -> None:
        """Write the unit, then enable and (re)start it, so a reinstall replaces a running
        service."""
        unit = render_unit(self.program_args, self.paths, self.path_env, self.extra_env)
        self.paths.ensure()
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        self.unit_path.write_text(unit, encoding="utf-8")
        for action in (["daemon-reload"], ["enable", UNIT_NAME], ["restart", UNIT_NAME]):
            self._checked(action)

    def remove_legacy(self) -> bool:
        """The service from before the rename only ever ran on macOS."""
        return False

    def stop(self) -> None:
        self._systemctl(["stop", UNIT_NAME])

    def uninstall(self) -> None:
        # Failure just means it was not enabled or running.
        self._systemctl(["disable", "--now", UNIT_NAME])
        self.unit_path.unlink(missing_ok=True)
        self._systemctl(["daemon-reload"])

    def status(self) -> ServiceStatus:
        result = self._systemctl(["status", "--no-pager", UNIT_NAME])
        return ServiceStatus(
            installed=self.unit_path.exists(),
            loaded=result.returncode == 0,
            # A stopped service's state is on stdout; a missing one's on stderr.
            detail=result.stdout or result.stderr,
        )

    def _systemctl(self, action: Sequence[str]) -> CommandResult:
        return self.runner([*SYSTEMCTL, *action])

    def _checked(self, action: Sequence[str]) -> None:
        result = self._systemctl(action)
        if result.returncode != 0:
            msg = f"{' '.join((*SYSTEMCTL, *action))} failed: {result.stderr.strip()}"
            raise ServiceError(msg)
