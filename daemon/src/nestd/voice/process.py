"""The voice worker process (B154): `worker.py serve` in the voice engine's venv, one
recording at a time, each answer one line of JSON.
"""

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, cast

from nestd.voice.install import WORKER, worker_env

logger = logging.getLogger(__name__)

# Loading a model from disk; Medium on a slow machine.
LOAD_TIME_LIMIT = 180.0
# The worker's lines are short, but a long recording's text is not.
_LINE_LIMIT = 1024 * 1024
_THREADS = min(4, os.cpu_count() or 1)


class VoiceWorkerError(Exception):
    """The worker stopped, said something unreadable or took too long."""


class Worker(Protocol):
    @property
    def alive(self) -> bool: ...

    async def transcribe(self, recording: Path, time_limit: float) -> str:
        """What was said in the recording; raises VoiceWorkerError, after which the worker
        is not alive."""
        ...

    async def close(self) -> None: ...


# Starts a worker with this Python for this model folder, once it has loaded the model.
type WorkerFactory = Callable[[Path, Path], Awaitable[Worker]]


class ProcessWorker:
    def __init__(self, process: asyncio.subprocess.Process, log: Path) -> None:
        self._process = process
        self._log = log

    @property
    def alive(self) -> bool:
        return self._process.returncode is None

    async def transcribe(self, recording: Path, time_limit: float) -> str:
        stdin = self._process.stdin
        if stdin is None or not self.alive:
            msg = "the voice worker is not running"
            raise VoiceWorkerError(msg)
        try:
            stdin.write(json.dumps({"path": str(recording)}).encode() + b"\n")
            await stdin.drain()
            answer = await self._read(time_limit)
        except BaseException as error:
            # Its answer may still come: a worker left running would give it to the next
            # recording, so any failure here, a cancel too, ends it.
            await asyncio.shield(self.close())
            if not isinstance(error, Exception):
                raise
            msg = str(error) if isinstance(error, VoiceWorkerError) else "the worker stopped"
            raise VoiceWorkerError(msg) from error
        text = answer.get("text")
        if isinstance(text, str):
            return text
        msg = str(answer.get("error", "the worker gave no text"))
        raise VoiceWorkerError(msg)

    async def _read(self, time_limit: float) -> dict[str, object]:
        stdout = self._process.stdout
        if stdout is None:
            msg = "the voice worker has no output"
            raise VoiceWorkerError(msg)
        try:
            line = await asyncio.wait_for(stdout.readline(), time_limit)
        except TimeoutError as error:
            msg = f"no answer within {int(time_limit)} s"
            raise VoiceWorkerError(msg) from error
        if not line:
            msg = f"the voice worker stopped: {self._last_words()}"
            raise VoiceWorkerError(msg)
        try:
            answer = json.loads(line)
        except ValueError as error:
            msg = "the voice worker said something unreadable"
            raise VoiceWorkerError(msg) from error
        if not isinstance(answer, dict):
            msg = "the voice worker said something unreadable"
            raise VoiceWorkerError(msg)
        return cast("dict[str, object]", answer)

    def _last_words(self) -> str:
        try:
            lines = self._log.read_text(errors="replace").strip().splitlines()
        except OSError:
            return "no log"
        return lines[-1][-300:] if lines else "no log"

    async def ready(self) -> None:
        answer = await self._read(LOAD_TIME_LIMIT)
        if answer.get("ready") is not True:
            msg = f"the voice worker did not start: {answer.get('error', answer)}"
            raise VoiceWorkerError(msg)

    async def close(self) -> None:
        if self.alive:
            if self._process.stdin is not None:
                self._process.stdin.close()
            with contextlib.suppress(ProcessLookupError):
                self._process.kill()
        await self._process.wait()


async def start_worker(python: Path, model_dir: Path) -> Worker:
    log = model_dir.parent.parent / "worker.log"
    with log.open("wb") as errors:
        try:
            process = await asyncio.create_subprocess_exec(
                str(python),
                "-I",
                str(WORKER),
                "serve",
                "--model-dir",
                str(model_dir),
                "--threads",
                str(_THREADS),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=errors,
                env=worker_env() | {"HF_HUB_OFFLINE": "1"},
                limit=_LINE_LIMIT,
            )
        except OSError as error:
            msg = f"could not start the voice worker: {error}"
            raise VoiceWorkerError(msg) from error
    worker = ProcessWorker(process, log)
    try:
        await worker.ready()
    except VoiceWorkerError:
        await worker.close()
        raise
    logger.info("voice worker started with %s", model_dir.name)
    return worker
