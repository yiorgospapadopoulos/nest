"""Start, follow and stop each folder's dev server: the repo's `[run] command` (B108).

One run per folder, shared by the chats working there. A run is the command under
`/bin/sh -c` in a process group of its own, so stopping it stops whatever it started.
Runs are not stored: they end with the daemon.
"""

import asyncio
import hashlib
import logging
import os
import signal
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from io import FileIO
from pathlib import Path

from nestd.clock import Clock
from nestd.config.models import RepoConfig
from nestd.errors import ConflictError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.shell_env import ShellEnvSource
from nestd.repos.service import RepoNotFoundError, RepoService
from nestd.runs.blocks import PortBlock, PortBlocks
from nestd.runs.listening import PortProbe
from nestd.runs.models import PortRange, RunOutput, RunState, RunStatus
from nestd.runs.output import OutputBuffer
from nestd.runs.prompt import ports_prompt
from nestd.sessions.models import PIXIE_REPO_PREFIX, Session
from nestd.sessions.ports import NO_PORTS, FolderPorts

# How often a live run's listening ports are read.
POLL_INTERVAL = timedelta(seconds=2)
# How long a run has to end after SIGTERM before it gets SIGKILL.
STOP_GRACE = timedelta(seconds=5)
CHUNK_BYTES = 65536
ALIVE: tuple[RunState, ...] = ("starting", "running")

# Sends a signal to a process group.
type GroupKill = Callable[[int, int], None]

logger = logging.getLogger(__name__)


class RunUnavailableError(ConflictError):
    pass


@dataclass(frozen=True)
class _Target:
    """Where a chat's run would be: its folder (None for a pixie's chat or one without a
    folder yet), whether that exists, and its repo (None when unknown).
    """

    folder: str | None
    exists: bool = False
    repo: RepoConfig | None = None

    @property
    def command(self) -> str | None:
        if self.repo is None or self.repo.run is None:
            return None
        return self.repo.run.command


@dataclass
class _FolderRun:
    """A folder's run: the live one, or the last one, whose output stays until the next."""

    folder: str
    repo: str
    command: str
    block: PortBlock | None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    buffer: OutputBuffer = field(default_factory=OutputBuffer)
    state: RunState = "stopped"
    listening: list[int] = field(default_factory=list[int])
    exit_code: int | None = None
    started_at: datetime | None = None
    group: int = 0
    reader: "asyncio.Task[None] | None" = None
    # Set while the user stops it, so its end is not taken for an exit.
    stopping: bool = False

    @property
    def alive(self) -> bool:
        return self.state in ALIVE


class RunManager:
    def __init__(
        self,
        *,
        bus: EventBus,
        blocks: PortBlocks,
        repos: RepoService,
        clock: Clock,
        logs_dir: Path,
        probe: PortProbe,
        shell_env: ShellEnvSource,
        base_env: Mapping[str, str],
        poll_interval: timedelta = POLL_INTERVAL,
        stop_grace: timedelta = STOP_GRACE,
        kill: GroupKill = os.killpg,
    ) -> None:
        """`probe` reads the ports a process group listens on (lsof); runs start in
        `base_env` with the user's login shell environment (`shell_env`) over it. `kill`
        signals a process group.
        """
        self._bus = bus
        self._blocks = blocks
        self._repos = repos
        self._clock = clock
        self._logs_dir = logs_dir
        self._probe = probe
        self._shell_env = shell_env
        self._base_env = base_env
        self._poll_seconds = poll_interval.total_seconds()
        self._grace_seconds = stop_grace.total_seconds()
        self._kill = kill
        self._runs: dict[str, _FolderRun] = {}

    async def status(self, session: Session) -> RunStatus:
        return await self._status(await self._target(session))

    async def output(self, session: Session) -> RunOutput:
        target = await self._target(session)
        run = None if target.folder is None else self._runs.get(target.folder)
        return RunOutput(folder=target.folder, text="" if run is None else run.buffer.text())

    async def start(self, session: Session) -> RunStatus:
        """Start the chat's folder's run; one that is alive already stays as it is. 409
        when the chat has no run (`available` false).
        """
        target = await self._target(session)
        if self._live(target.folder) is None:
            await self._start(*_runnable(target))
        return await self._status(target)

    async def stop(self, session: Session) -> RunStatus:
        """Stop the chat's folder's run; one that is not alive stays as it is."""
        target = await self._target(session)
        run = None if target.folder is None else self._runs.get(target.folder)
        if run is not None:
            await self._stop(run)
        return await self._status(target)

    async def restart(self, session: Session) -> RunStatus:
        """Stop the run, then start it again with the repo's command as it is now."""
        target = await self._target(session)
        folder, repo, command = _runnable(target)
        run = self._runs.get(folder)
        if run is not None:
            await self._stop(run)
        await self._start(folder, repo, command)
        return await self._status(target)

    async def agent_ports(self, session: Session) -> FolderPorts:
        """The ports and the paragraph for the agent of a run opening now."""
        target = await self._target(session)
        block = await self._block(target)
        if block is None:
            return NO_PORTS
        run = self._live(target.folder)
        listening = run.listening[0] if run is not None and run.listening else None
        return FolderPorts(env=block.env(), prompt=ports_prompt(block, target.command, listening))

    async def setup_env(self, repo: RepoConfig, folder: Path) -> dict[str, str]:
        """The ports of a new worktree, for its setup commands."""
        block = await self._blocks.block_for(str(folder), repo.name)
        return {} if block is None else block.env()

    async def set_up(self, repo: RepoConfig, folder: Path) -> None:
        """A new worktree's setup succeeded: its run starts when the repo asks for it."""
        if repo.run is None or not repo.run.after_setup:
            return
        try:
            await self._start(str(folder), repo, repo.run.command)
        except Exception as error:
            logger.warning("could not start the run in %s (%s)", folder, error)

    async def removing(self, folder: Path) -> None:
        """Nest removes the worktree: its run stops and its ports are freed."""
        await self._forget(str(folder))

    async def forget_repo(self, repo: str) -> None:
        """The repo was removed: the runs in its folders stop and their ports are freed."""
        folders = {run.folder for run in self._runs.values() if run.repo == repo}
        for folder in folders:
            await self._forget(folder)
        await self._blocks.free_repo(repo)

    async def shutdown(self) -> None:
        """Stop every run, as the daemon stops."""
        runs = [run for run in self._runs.values() if run.alive]
        results = await asyncio.gather(*(self._stop(run) for run in runs), return_exceptions=True)
        for run, result in zip(runs, results, strict=True):
            if isinstance(result, Exception):
                logger.error("stopping the run in %s failed", run.folder, exc_info=result)

    async def _forget(self, folder: str) -> None:
        run = self._runs.get(folder)
        if run is not None:
            await self._stop(run)
            del self._runs[folder]
        await self._blocks.free(folder)

    async def _target(self, session: Session) -> _Target:
        if (
            session.pixie_id is not None
            or session.repo.startswith(PIXIE_REPO_PREFIX)
            or session.cwd is None
        ):
            return _Target(None)
        folder = session.cwd
        try:
            repo = self._repos.get(session.repo)
        except RepoNotFoundError:
            repo = None
        return _Target(str(folder), await asyncio.to_thread(folder.is_dir), repo)

    async def _block(self, target: _Target) -> PortBlock | None:
        if target.folder is None or target.repo is None or not target.exists:
            return None
        return await self._blocks.block_for(target.folder, target.repo.name)

    def _live(self, folder: str | None) -> _FolderRun | None:
        run = None if folder is None else self._runs.get(folder)
        return run if run is not None and run.alive else None

    async def _status(self, target: _Target) -> RunStatus:
        block = await self._block(target)
        run = None if target.folder is None else self._runs.get(target.folder)
        live = run if run is not None and run.alive else None
        # A run keeps its command while alive, so it can still be stopped.
        command = live.command if live is not None else target.command
        available = target.exists and target.repo is not None and command is not None
        return _status(target.folder, command if available else None, block, run)

    async def _start(self, folder: str, repo: RepoConfig, command: str) -> None:
        run = self._runs.get(folder)
        if run is None:
            run = self._runs.setdefault(folder, _FolderRun(folder, repo.name, command, None))
        async with run.lock:
            if run.alive:
                return
            block = await self._blocks.block_for(folder, repo.name)
            env = {
                **self._base_env,
                **await self._shell_env(),
                **({} if block is None else block.env()),
            }
            self._logs_dir.mkdir(parents=True, exist_ok=True)
            # Each start begins the log afresh, as it does the output buffer.
            log = (self._logs_dir / f"run-{_folder_hash(folder)}.log").open("wb", buffering=0)
            try:
                process = await asyncio.create_subprocess_exec(
                    "/bin/sh",
                    "-c",
                    command,
                    cwd=folder,
                    env=env,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    # A process group of its own, so stopping it stops its children too.
                    start_new_session=True,
                )
            except BaseException:
                log.close()
                raise
            run.repo, run.command, run.block = repo.name, command, block
            run.state, run.listening, run.exit_code = "starting", [], None
            run.started_at = self._clock.now().replace(microsecond=0)
            run.group = process.pid
            run.buffer.clear()
            header = f"$ {command}\n"
            run.buffer.add_text(header)
            log.write(header.encode())
            await self._output(run, header)
            await self._changed(run)
            run.reader = asyncio.create_task(self._follow(run, process, log))

    async def _follow(
        self, run: _FolderRun, process: asyncio.subprocess.Process, log: FileIO
    ) -> None:
        """Read the run's output until it ends; one that was not stopped exited."""
        poller = asyncio.create_task(self._poll(run))
        stdout = process.stdout
        assert stdout is not None  # noqa: S101 (a pipe was asked for)
        try:
            while chunk := await stdout.read(CHUNK_BYTES):
                log.write(chunk)
                text = run.buffer.add(chunk)
                if text:
                    await self._output(run, text)
            exit_code = await process.wait()
        finally:
            log.close()
            poller.cancel()
            await asyncio.gather(poller, return_exceptions=True)
        if not run.stopping:
            run.state, run.listening, run.exit_code = "exited", [], exit_code
            await self._changed(run)

    async def _poll(self, run: _FolderRun) -> None:
        """Follow the ports the run listens on; announced only when they change."""
        while True:
            await asyncio.sleep(self._poll_seconds)
            ports = await self._probe(run.group)
            if not run.alive or run.stopping:
                return
            state: RunState = "running" if ports else "starting"
            if (state, ports) != (run.state, run.listening):
                run.state, run.listening = state, ports
                await self._changed(run)

    async def _stop(self, run: _FolderRun) -> None:
        """SIGTERM to the group, SIGKILL when it has not ended after the grace time. Its
        output is read to the end unless something outside the group keeps it open.
        """
        async with run.lock:
            reader = run.reader
            if not run.alive or reader is None:
                return
            run.stopping = True
            try:
                self._signal(run.group, signal.SIGTERM)
                if not await self._ended(reader):
                    self._signal(run.group, signal.SIGKILL)
                    if not await self._ended(reader):
                        logger.warning("the run in %s holds its output open", run.folder)
                        reader.cancel()
                        await asyncio.gather(reader, return_exceptions=True)
            finally:
                run.stopping = False
            run.state, run.listening, run.exit_code, run.started_at = "stopped", [], None, None
            await self._changed(run)

    async def _ended(self, reader: "asyncio.Task[None]") -> bool:
        done, _ = await asyncio.wait({reader}, timeout=self._grace_seconds)
        return bool(done)

    def _signal(self, group: int, number: int) -> None:
        # Every process of the group may have ended already.
        with suppress(ProcessLookupError):
            self._kill(group, number)

    async def _output(self, run: _FolderRun, text: str) -> None:
        await self._bus.publish_ephemeral(types.RUN_OUTPUT, {"folder": run.folder, "text": text})

    async def _changed(self, run: _FolderRun) -> None:
        status = _status(run.folder, run.command, run.block, run)
        await self._bus.publish_ephemeral(
            types.RUN_CHANGED,
            {"folder": run.folder, "repo": run.repo, "status": status.model_dump(mode="json")},
        )


def _status(
    folder: str | None, command: str | None, block: PortBlock | None, run: _FolderRun | None
) -> RunStatus:
    return RunStatus(
        available=command is not None,
        command=command,
        folder=folder,
        block=None if block is None else PortRange(start=block.start, end=block.end),
        state="stopped" if run is None else run.state,
        listening=[] if run is None else run.listening,
        exit_code=None if run is None else run.exit_code,
        started_at=None if run is None else run.started_at,
    )


def _runnable(target: _Target) -> tuple[str, RepoConfig, str]:
    """The folder, repo and command to start; 409 when the chat has no run."""
    command = target.command
    if target.folder is None or target.repo is None or command is None or not target.exists:
        msg = "this chat has no dev server command to run"
        raise RunUnavailableError(msg)
    return target.folder, target.repo, command


def _folder_hash(folder: str) -> str:
    return hashlib.sha256(folder.encode()).hexdigest()[:12]
