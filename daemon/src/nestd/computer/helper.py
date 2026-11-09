"""The daemon's side of the Nest Computer helper app (B150): it holds the Accessibility and
Screen Recording permissions, so the Python program agents' shells run never does (D178).

The helper listens on a Unix socket and answers only the daemon's pid; requests and replies
are JSON lines (`plans/b150/design.md`, "Helper protocol").
"""

import asyncio
import contextlib
import hashlib
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

from pydantic import JsonValue

HELPER_NAME = "Nest Computer.app"
HELPER_ID = "local.nest.computer"
MAC_APP_ENV = "NEST_MAC_APP"
DEFAULT_MAC_APP = Path("/Applications/Nest.app")
# Unix socket paths longer than this fail on macOS (the limit is 104 bytes).
_SOCKET_MAX = 100
_START_SECONDS = 8.0
CALL_SECONDS = 30.0
# The longest reply line: a screenshot is a base64 PNG of a few megabytes, far past
# asyncio's 64 KB default. The helper reads requests up to 4 MB.
_LINE_MAX = 32 * 1024 * 1024

type JsonObject = dict[str, JsonValue]
# Starts the helper app with these arguments (`open -g -a <app> --args ...` by default).
type Launcher = Callable[[Path, Sequence[str]], Awaitable[None]]


class HelperError(Exception):
    """The helper refused or failed a request; `code` is the protocol's error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def helper_app(env: Mapping[str, str]) -> Path:
    mac_app = Path(env.get(MAC_APP_ENV) or DEFAULT_MAC_APP)
    return mac_app / "Contents" / "Helpers" / HELPER_NAME


def socket_path(data_dir: Path) -> Path:
    path = data_dir / "computer" / "helper.sock"
    if len(os.fsencode(path)) <= _SOCKET_MAX:
        return path
    # A long test-copy data folder: a short fixed place, as the temp folder is long too.
    digest = hashlib.sha256(os.fsencode(data_dir)).hexdigest()[:8]
    return Path(f"/tmp/nest-{os.getuid()}-{digest}.sock")  # noqa: S108


async def open_app(app: Path, args: Sequence[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/open",
        "-g",
        "-a",
        str(app),
        "--args",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise HelperError("failed", f"Could not start {HELPER_NAME}: {stderr.decode().strip()}")


class Helper:
    """One connection to the helper, started on first use and restarted if it went away."""

    def __init__(self, app: Path, socket: Path, launcher: Launcher = open_app) -> None:
        self._app = app
        self._socket = socket
        self._launcher = launcher
        self._lock = asyncio.Lock()
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[JsonObject]] = {}
        self._next_id = 0

    @property
    def installed(self) -> bool:
        return self._app.is_dir()

    async def call(
        self, op: str, args: JsonObject | None = None, time_limit: float = CALL_SECONDS
    ) -> JsonObject:
        writer = await self._connected()
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future[JsonObject] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        line = json.dumps({"id": request_id, "op": op, "args": args or {}}) + "\n"
        try:
            writer.write(line.encode())
            await writer.drain()
            return await asyncio.wait_for(future, time_limit)
        except TimeoutError as error:
            raise HelperError("failed", f"{HELPER_NAME} did not answer {op} in time.") from error
        finally:
            self._pending.pop(request_id, None)

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        if self._writer is not None:
            self._writer.close()
        self._writer = None
        self._reader_task = None

    async def _connected(self) -> asyncio.StreamWriter:
        async with self._lock:
            if self._writer is not None and not self._writer.is_closing():
                return self._writer
            if not self.installed:
                raise HelperError("failed", f"{HELPER_NAME} is not installed with Nest.app.")
            reader, writer = await self._connect_or_start()
            self._writer = writer
            self._reader_task = asyncio.create_task(self._read(reader))
            return writer

    async def _connect_or_start(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        with contextlib.suppress(OSError):
            return await asyncio.open_unix_connection(self._socket, limit=_LINE_MAX)
        self._socket.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        await self._launcher(
            self._app, ["--socket", str(self._socket), "--controller", str(os.getpid())]
        )
        deadline = asyncio.get_running_loop().time() + _START_SECONDS
        while True:
            try:
                return await asyncio.open_unix_connection(self._socket, limit=_LINE_MAX)
            except OSError as error:
                if asyncio.get_running_loop().time() > deadline:
                    raise HelperError("failed", f"{HELPER_NAME} did not start.") from error
                await asyncio.sleep(0.1)

    async def _read(self, reader: asyncio.StreamReader) -> None:
        try:
            while line := await reader.readline():
                self._settle(json.loads(line))
        finally:
            self._writer = None
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(HelperError("failed", f"{HELPER_NAME} went away."))

    def _settle(self, reply: object) -> None:
        if not isinstance(reply, dict):
            return
        message = cast(JsonObject, reply)
        request_id = message.get("id")
        future = self._pending.get(request_id) if isinstance(request_id, int) else None
        if future is None or future.done():
            return
        if message.get("ok") is True:
            result = message.get("result")
            future.set_result(cast(JsonObject, result) if isinstance(result, dict) else {})
            return
        error = message.get("error")
        detail = cast(JsonObject, error) if isinstance(error, dict) else {}
        future.set_exception(
            HelperError(str(detail.get("code", "failed")), str(detail.get("message", "")))
        )
