"""Voice input (B154): its state, fetching it, and turning recordings into text.

One worker at most, for the chosen model, started on the first recording and stopped after
a few idle minutes, so the model's memory is not held while nobody talks.
"""

import asyncio
import contextlib
import logging
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nestd.config.models import VoiceSettings
from nestd.errors import ConflictError, NestError
from nestd.platform.base import PlatformName
from nestd.voice.audio import SHORTEST_SECONDS, recording_seconds
from nestd.voice.install import (
    CommandRunner,
    VoiceFolder,
    VoiceInstallError,
    install_engine,
    install_model,
    run_command,
)
from nestd.voice.models import (
    ENGINE_MB,
    MODELS,
    InstallStep,
    VoiceModel,
    VoiceModelInfo,
    VoiceStatus,
    default_model,
    voice_model,
)
from nestd.voice.process import VoiceWorkerError, Worker, WorkerFactory, start_worker

logger = logging.getLogger(__name__)

IDLE_SECONDS = 300.0
# Whisper on a CPU takes a fraction of the recording's length; this is room for a slow one.
_MIN_TIME_LIMIT = 60.0
_TIME_PER_SECOND = 2.0


@dataclass(frozen=True)
class VoiceSetup:
    """What voice input reaches: the commands that fetch it and the worker it starts."""

    run: CommandRunner = run_command
    workers: WorkerFactory = start_worker


class VoiceNotReadyError(ConflictError):
    pass


class VoiceFailedError(NestError):
    status_code = 502


class VoiceService:
    def __init__(
        self,
        root: Path,
        platform: PlatformName,
        settings: Callable[[], VoiceSettings],
        setup: VoiceSetup | None = None,
        python: Path = Path(sys.executable),
    ) -> None:
        """`root` is `<data_dir>/voice`; `settings` is read at each use, so a new choice
        applies at once; `python` makes the engine's venv.
        """
        self.folder = VoiceFolder(root)
        self._platform: PlatformName = platform
        self._settings = settings
        reach = setup or VoiceSetup()
        self._run = reach.run
        self._workers = reach.workers
        self._python = python
        self._install: asyncio.Task[None] | None = None
        self._step: InstallStep | None = None
        self._failure: str | None = None
        self._worker: Worker | None = None
        self._lock = asyncio.Lock()
        self._idle: asyncio.Task[None] | None = None

    def model(self) -> VoiceModel:
        chosen = self._settings().model
        return voice_model(chosen if chosen is not None else default_model(self._platform))

    def status(self) -> VoiceStatus:
        chosen = self.model()
        engine_ready = self.folder.engine_ready()
        model_ready = self.folder.model_ready(chosen)
        if self._install is not None:
            state = "installing"
        elif engine_ready and model_ready:
            state = "ready"
        elif self._failure is not None:
            state = "install_failed"
        else:
            state = "not_installed"
        download = (0 if engine_ready else ENGINE_MB) + (0 if model_ready else chosen.size_mb)
        return VoiceStatus(
            state=state,
            model=chosen.id,
            default_model=default_model(self._platform),
            models=[VoiceModelInfo(id=m.id, label=m.label, size_mb=m.size_mb) for m in MODELS],
            download_mb=download,
            step=self._step if state == "installing" else None,
            detail=self._failure if state == "install_failed" else None,
        )

    def start_install(self) -> VoiceStatus:
        """Fetch what the chosen model needs, in the background, unless it is there or
        being fetched.
        """
        if self._install is None and self.status().state != "ready":
            self._step = "model" if self.folder.engine_ready() else "packages"
            self._install = asyncio.create_task(self._fetch())
        return self.status()

    async def _fetch(self) -> None:
        chosen = self.model()
        self._failure = None
        try:
            if not self.folder.engine_ready():
                self._step = "packages"
                await install_engine(self.folder, self._python, self._run)
            if not self.folder.model_ready(chosen):
                self._step = "model"
                await install_model(self.folder, chosen, self._run)
        except (VoiceInstallError, OSError) as error:
            self._failure = str(error) or type(error).__name__
            logger.warning("could not set up voice input: %s", self._failure)
        else:
            logger.info("voice input is ready with %s", chosen.id)
        finally:
            self._install = None
            self._step = None

    async def remove(self) -> VoiceStatus:
        """Delete the engine and models; 409 while they are being fetched."""
        self._refuse_while_installing()
        async with self._lock:
            # An install may have started while a recording held the lock.
            self._refuse_while_installing()
            await self._stop_worker()
            self._failure = None
            await asyncio.to_thread(self.folder.remove)
        return self.status()

    def _refuse_while_installing(self) -> None:
        if self._install is not None:
            msg = "voice input is being downloaded: wait until it is done"
            raise ConflictError(msg)

    def check_model_change(self) -> None:
        """409 while downloading: the download in progress would delete the model chosen."""
        self._refuse_while_installing()

    async def model_changed(self) -> None:
        """The next recording starts a worker with the new choice."""
        async with self._lock:
            await self._stop_worker()

    async def transcribe(self, recording: bytes) -> str:
        seconds = recording_seconds(recording)
        if self.status().state != "ready":
            msg = "voice input is not set up: download it first"
            raise VoiceNotReadyError(msg)
        if seconds < SHORTEST_SECONDS:
            return ""
        async with self._lock:
            self._cancel_idle()
            try:
                return await self._transcribe(recording, seconds)
            finally:
                self._idle = asyncio.create_task(self._stop_when_idle())

    async def _transcribe(self, recording: bytes, seconds: float) -> str:
        chosen = self.model()
        self.folder.recordings.mkdir(parents=True, exist_ok=True)
        path = self.folder.recordings / f"{secrets.token_hex(8)}.wav"
        await asyncio.to_thread(path.write_bytes, recording)
        try:
            worker = await self._ready_worker(chosen)
            time_limit = max(_MIN_TIME_LIMIT, seconds * _TIME_PER_SECOND)
            return await worker.transcribe(path, time_limit)
        except VoiceWorkerError as error:
            logger.warning("voice input failed: %s", error)
            msg = f"voice input failed: {error}"
            raise VoiceFailedError(msg) from error
        finally:
            path.unlink(missing_ok=True)

    async def _ready_worker(self, chosen: VoiceModel) -> Worker:
        if self._worker is not None and self._worker.alive:
            return self._worker
        self._worker = await self._workers(self.folder.python, self.folder.model_dir(chosen))
        return self._worker

    async def _stop_when_idle(self) -> None:
        await asyncio.sleep(IDLE_SECONDS)
        async with self._lock:
            await self._stop_worker()

    def _cancel_idle(self) -> None:
        idle, self._idle = self._idle, None
        if idle is not None and idle is not asyncio.current_task():
            idle.cancel()

    async def _stop_worker(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            await worker.close()

    async def close(self) -> None:
        self._cancel_idle()
        install, self._install = self._install, None
        if install is not None:
            install.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await install
        await self._stop_worker()
