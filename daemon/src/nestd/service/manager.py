"""The background service of the platform the daemon runs on."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from nestd.paths import AppPaths
from nestd.platform import Platform
from nestd.platform.linux import xdg_dir
from nestd.service.base import CommandRunner, ServiceManager
from nestd.service.launchd import LaunchdService
from nestd.service.systemd import SystemdService


def service_manager(
    platform: Platform,
    paths: AppPaths,
    home: Path,
    env: Mapping[str, str],
    uid: int,
    runner: CommandRunner,
    program_args: Sequence[str],
) -> ServiceManager:
    path_env = platform.service_path(home)
    match platform.name:
        case "macos":
            return LaunchdService(
                paths=paths,
                launch_agents_dir=home / "Library" / "LaunchAgents",
                uid=uid,
                runner=runner,
                program_args=program_args,
                path_env=path_env,
            )
        case "linux":
            return SystemdService(
                paths=paths,
                unit_dir=xdg_dir(env, "XDG_CONFIG_HOME", home / ".config") / "systemd" / "user",
                runner=runner,
                program_args=program_args,
                path_env=path_env,
            )
