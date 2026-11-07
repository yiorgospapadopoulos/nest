"""What the checks ask the machine. Everything has a time limit, as a locked keyring or a
stuck network can hang, and `nest doctor` must always finish.
"""

import json
import os
import platform as python_platform
import shutil
import sqlite3
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import JsonValue

from nestd.config.errors import ConfigError
from nestd.config.loader import load_settings
from nestd.config.models import Settings
from nestd.paths import AppPaths, is_packaged
from nestd.platform import Platform
from nestd.service.base import CommandResult, ServiceManager, run_command
from nestd.service.manager import service_manager

COMMAND_LIMIT = 10.0
SECRET_LIMIT = 10.0
HEALTH_LIMIT = 2.0
HTTP_OK = 200
NOT_FOUND = 127
TIMED_OUT = 124

# Runs a command with an environment and a limit in seconds; never raises.
type Runner = Callable[[Sequence[str], Mapping[str, str], float], CommandResult]


def run_limited(
    args: Sequence[str], env: Mapping[str, str], limit: float = COMMAND_LIMIT
) -> CommandResult:
    try:
        done = subprocess.run(  # noqa: S603
            list(args),
            capture_output=True,
            text=True,
            check=False,
            env=dict(env),
            timeout=limit,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(TIMED_OUT, "", "timed out")
    except OSError as error:
        return CommandResult(NOT_FOUND, "", str(error))
    return CommandResult(done.returncode, done.stdout, done.stderr)


def answers_health(port: int) -> bool:
    try:
        response = httpx.get(
            f"http://127.0.0.1:{port}/api/health", timeout=HEALTH_LIMIT, trust_env=False
        )
    except httpx.HTTPError:
        return False
    return response.status_code == HTTP_OK


def within_limit(read: Callable[[], None], limit: float = SECRET_LIMIT) -> str | None:
    """Runs `read` on a thread nothing waits for at exit: why it failed, or None."""
    failure: list[str] = ["it did not answer in time"]

    def attempt() -> None:
        try:
            read()
            failure.clear()
        except Exception as error:
            failure[:] = [str(error) or type(error).__name__]

    thread = threading.Thread(target=attempt, name="nest-doctor", daemon=True)
    thread.start()
    thread.join(limit)
    return failure[0] if failure else None


def json_object(text: str) -> dict[str, JsonValue] | None:
    try:
        value: JsonValue = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


@dataclass(frozen=True)
class Machine:
    paths: AppPaths
    platform: Platform
    home: Path
    env: Mapping[str, str]
    port: int
    service: ServiceManager
    # Reads a secret, raising when the store is missing or locked.
    read_secret: Callable[[], None]
    # Whether this Nest came from a release.
    packaged: bool
    run: Runner = run_limited
    healthy: Callable[[int], bool] = answers_health
    disk_free: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free

    @property
    def search_env(self) -> dict[str, str]:
        """The environment the service's own PATH gives, then the caller's."""
        path = os.pathsep.join(
            part for part in (self.platform.service_path(self.home), self.env.get("PATH")) if part
        )
        return {**self.env, "PATH": path}

    def which(self, program: str) -> str | None:
        return shutil.which(program, path=self.search_env["PATH"])

    def command(self, *args: str, limit: float = COMMAND_LIMIT) -> CommandResult:
        return self.run(args, self.search_env, limit)

    def settings(self) -> Settings | None:
        try:
            return load_settings(self.paths)
        except ConfigError:
            return None

    def database(self, query: str) -> bool:
        """Whether the read-only query finds a row. False with no database or table yet."""
        database = self.paths.db_path
        if not database.is_file():
            return False
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=2.0)
        except sqlite3.Error:
            return False
        try:
            return connection.execute(query).fetchone() is not None
        except sqlite3.Error:
            return False
        finally:
            connection.close()


def this_machine(
    paths: AppPaths,
    platform: Platform,
    home: Path,
    env: Mapping[str, str],
    port: int,
    read_secret: Callable[[], None],
) -> Machine:
    program = [sys.executable, "-m", "nestd", "serve"]
    service = service_manager(platform, paths, home, env, os.getuid(), run_command, program)
    return Machine(paths, platform, home, env, port, service, read_secret, is_packaged())


def system_line() -> str:
    return f"{python_platform.system()} {python_platform.release()} {python_platform.machine()}"
