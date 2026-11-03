"""The process environment the CLI acts on, injectable so tests never touch the real system."""

import os
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from fastapi import FastAPI

from nestd.auth.secrets import KeyringSecretStore, SecretStore
from nestd.clock import Clock, SystemClock
from nestd.platform import Platform, current_platform
from nestd.server import run_uvicorn
from nestd.service.base import CommandRunner, run_command
from nestd.service.restart import Restarter, terminate_self

type ServeRunner = Callable[[FastAPI, int], Awaitable[None]]


@dataclass(frozen=True)
class Runtime:
    env: Mapping[str, str]
    home: Path
    uid: int
    executable: str
    platform: Platform
    secrets: SecretStore
    clock: Clock
    run_command: CommandRunner
    serve: ServeRunner
    restart: Restarter
    out: TextIO
    err: TextIO


def default_runtime() -> Runtime:
    platform = current_platform()
    return Runtime(
        env=os.environ,
        home=Path.home(),
        uid=os.getuid(),
        executable=sys.executable,
        platform=platform,
        secrets=KeyringSecretStore(platform.secret_store_help),
        clock=SystemClock(),
        run_command=run_command,
        serve=run_uvicorn,
        restart=terminate_self,
        out=sys.stdout,
        err=sys.stderr,
    )
