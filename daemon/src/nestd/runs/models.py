"""What clients see of a folder's run (B108). A wire contract: the Mac and the phone read it."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# `stopped`: never started, or stopped by the user; `starting`: alive, listening on no port
# yet; `running`: alive and listening; `exited`: ended on its own, `exit_code` set.
type RunState = Literal["stopped", "starting", "running", "exited"]


class PortRange(BaseModel):
    start: int
    end: int


class RunStatus(BaseModel):
    # The repo has a `[run] command` and the chat is a project chat whose folder exists;
    # when false, `command` is null and clients show no Run control.
    available: bool
    command: str | None
    # Where the chat works; chats in the same folder share its ports and run. Null for a
    # chat without a folder yet, or a pixie's.
    folder: str | None
    # Null when the folder could get no ports.
    block: PortRange | None
    state: RunState
    # Ascending; may hold ports outside the block, of a server that ignored NEST_PORT.
    listening: list[int]
    exit_code: int | None
    # When the run that is alive, or that exited, started; null while stopped.
    started_at: datetime | None


class RunOutput(BaseModel):
    folder: str | None
    # The last lines of output, raw (terminal escapes included).
    text: str
