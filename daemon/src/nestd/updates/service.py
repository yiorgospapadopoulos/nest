"""Following the newest engines: check when an app opens, prepare in the background, swap
when the user relaunches. See `boot.py` for what happens at the restart.

A check or prepare that fails shows nothing: it is logged, and the next app open tries
again. Nothing here changes the running environment, the base or the repository.
"""

import asyncio
import logging
import os
import shutil
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel

from nestd.engine.acp_install import NpmRunner, remove_old, run_npm
from nestd.errors import ConflictError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.paths import AppPaths, is_packaged
from nestd.platform import PlatformName
from nestd.providers.acp_engines import ACP_ENGINES, BASE_ENGINES
from nestd.providers.shell_env import ShellEnvSource
from nestd.updates.app import AppFile, AppUpdate, AppUpdater
from nestd.updates.boot import TrialWatch
from nestd.updates.build import (
    EnvironmentBuilder,
    Plan,
    PrepareError,
    SelfcheckRunner,
    UpdaterUnavailableError,
    UvRunner,
    run_selfcheck,
    run_uv,
)
from nestd.updates.engines import (
    EngineUpdate,
    Versions,
    changes,
    followed_engines,
    npm_engines,
    running_versions,
)
from nestd.updates.environments import (
    kept_folders,
    kept_versions,
    remove_unused,
    running_environment,
    usable,
)
from nestd.updates.manifest import Manifest
from nestd.updates.registry import RegistryError, latest_on_npm, latest_on_pypi
from nestd.updates.state import StateFile, UpdateState, confirmed, relaunched, undone
from nestd.updates.versions import is_newer

logger = logging.getLogger(__name__)

REGISTRY_TIME_LIMIT = 30.0
# How often a daemon in an environment asks its own health check.
HEALTH_EVERY_SECONDS = 1.0

type Phase = Literal["checking", "preparing"]
# Whether the daemon on this port answers its health check.
type HealthCheck = Callable[[int], Awaitable[bool]]


class NothingToRelaunchError(ConflictError):
    def __init__(self) -> None:
        super().__init__("No update is ready")


class NothingToUndoError(ConflictError):
    def __init__(self) -> None:
        super().__init__("There is nothing to go back to")


class EngineUpdates(BaseModel):
    """`GET /api/updates`."""

    state: Literal["none", "checking", "preparing", "ready"]
    # What Relaunch changes; only while `state` is ready.
    engines: list[EngineUpdate]
    # A new Nest; only the Mac and Linux apps offer it.
    app: AppUpdate | None = None
    # The app of the daemon now running: an app of another version swaps to it.
    app_file: AppFile | None = None
    # Chats a relaunch would interrupt right now.
    busy_chats: int
    can_undo: bool
    # A plain sentence for the user, until dismissed.
    notice: str | None


async def answers_health(port: int) -> bool:
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5.0) as client:
            response = await client.get(f"http://127.0.0.1:{port}/api/health")
    except httpx.HTTPError:
        return False
    return response.status_code == 200


@dataclass(frozen=True)
class UpdateSetup:
    """What the updater reaches outside Nest, replaced in tests."""

    # For the registries; None is the network.
    transport: httpx.AsyncBaseTransport | None = None
    uv: UvRunner = run_uv
    npm: NpmRunner = run_npm
    selfcheck: SelfcheckRunner = run_selfcheck
    healthy: HealthCheck = answers_health
    versions: Callable[[], Versions] = running_versions
    # This process's environment.
    prefix: Path = Path(sys.prefix)
    # Whether this Nest came from a release, so it follows releases.
    packaged: Callable[[], bool] = is_packaged


class UpdateService:
    def __init__(
        self,
        *,
        paths: AppPaths,
        platform: PlatformName,
        bus: EventBus,
        shell_env: ShellEnvSource,
        busy_chats: Callable[[], int],
        port: Callable[[], int],
        setup: UpdateSetup,
    ) -> None:
        """`busy_chats` counts the chats a relaunch would interrupt and `port` is the one
        the daemon serves on.
        """
        root = paths.environments_dir
        engines_dir = paths.engines_dir
        self._root = root
        self._engines_dir = engines_dir
        self._bin_dir = paths.bin_dir
        self._bus = bus
        self._busy_chats = busy_chats
        self._port = port
        self._setup = setup
        self._files = StateFile(root)
        self._lock = asyncio.Lock()
        self._phase: Phase | None = None
        self._task: asyncio.Task[None] | None = None
        self._settling: asyncio.Task[None] | None = None
        self._shell_env = shell_env
        self._builder = EnvironmentBuilder(
            root, engines_dir, setup.uv, setup.npm, setup.selfcheck, self._env
        )
        self._app = AppUpdater(
            paths=paths,
            platform=platform,
            packaged=setup.packaged(),
            uv=setup.uv,
            selfcheck=setup.selfcheck,
            env=self._env,
            transport=setup.transport,
        )
        # The running watch of a daemon in an environment, from the boot switch.
        self.watch: TrialWatch | None = None

    async def start(self) -> None:
        """After the daemon started: confirm this boot, then clear what nothing needs."""
        self._settling = asyncio.create_task(self._settle())

    async def stop(self) -> None:
        tasks = [task for task in (self._settling, self._task) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._settling = None
        self._task = None
        self._phase = None

    async def settled(self) -> None:
        """Wait for what `start` began."""
        if self._settling is not None:
            await self._settling

    async def stop_when_done(self) -> None:
        """Wait for a check under way and its prepare."""
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    async def status(self) -> EngineUpdates:
        state, ready = await asyncio.to_thread(self._read)
        app = await asyncio.to_thread(self._app.state)
        engines: list[EngineUpdate] = []
        if ready is not None:
            now = await asyncio.to_thread(self._setup.versions)
            engines = changes(now, ready.packages, ready.shown)
        can_undo = state.previous is not None or await asyncio.to_thread(self._app.can_undo)
        return EngineUpdates(
            state="ready" if ready is not None or app.ready else self._phase or "none",
            engines=engines,
            app=app.ready,
            app_file=await asyncio.to_thread(self._app.app_file),
            busy_chats=self._busy_chats(),
            can_undo=can_undo,
            notice=app.notice or state.notice,
        )

    async def check(self) -> EngineUpdates:
        """Start a check, which prepares what it finds, unless one runs."""
        async with self._lock:
            if self._task is None:
                self._phase = "checking"
                self._task = asyncio.create_task(self._check_and_prepare())
        return await self.status()

    async def relaunch(self) -> None:
        """Make the ready Nest or environment the one to run; the caller then restarts the
        daemon. A new Nest goes first: environments are tied to the base they were made from,
        so engines are prepared again on the new one.
        """
        async with self._lock:
            state, ready = await asyncio.to_thread(self._read)
            if (await asyncio.to_thread(self._app.state)).ready is not None:
                await self._app.relaunch(self._port())
                dropped = state.model_copy(update={"ready": None})
                await asyncio.to_thread(self._files.save, dropped)
                await self._announce()
                return
            if ready is None:
                raise NothingToRelaunchError
            await asyncio.to_thread(self._files.save, relaunched(state))
        await self._announce()

    async def undo(self) -> None:
        """Make the previous environment the one to run; the caller then restarts the daemon."""
        async with self._lock:
            state = await asyncio.to_thread(self._files.load)
            if await asyncio.to_thread(self._app.can_undo):
                await self._app.undo()
                await self._announce()
                return
            if state.previous is None:
                raise NothingToUndoError
            await asyncio.to_thread(self._files.save, undone(state))
        await self._announce()

    async def dismiss(self) -> EngineUpdates:
        async with self._lock:
            state = await asyncio.to_thread(self._files.load)
            if state.notice is not None:
                cleared = state.model_copy(update={"notice": None})
                await asyncio.to_thread(self._files.save, cleared)
            await asyncio.to_thread(self._app.dismiss)
        await self._announce()
        return await self.status()

    def _read(self) -> tuple[UpdateState, Manifest | None]:
        state = self._files.load()
        if state.ready is None:
            return state, None
        return state, usable(self._root, state.ready, state.base_fingerprint)

    async def _env(self) -> Mapping[str, str]:
        env = {**os.environ, **await self._shell_env()}
        # Where the install script puts `uv` on a machine that had none.
        return {**env, "PATH": os.pathsep.join((env.get("PATH", ""), str(self._bin_dir)))}

    async def _announce(self) -> None:
        status = await self.status()
        await self._bus.publish_ephemeral(types.UPDATES_CHANGED, status.model_dump(mode="json"))

    async def _check_and_prepare(self) -> None:
        try:
            await self._announce()
            if not await self._app_ready():
                await self._prepare_what_is_new()
        except UpdaterUnavailableError as error:
            logger.info("engine updates are not available here: %s", error)
        except (PrepareError, RegistryError, OSError) as error:
            logger.warning("could not prepare an engine update: %s", error)
        except Exception:
            logger.exception("could not prepare an engine update")
        finally:
            self._phase = None
            self._task = None
        await self._announce()

    async def _app_ready(self) -> bool:
        """A new Nest makes any engine environment built now useless, so it goes first. One
        that cannot be prepared is logged and does not stop engine updates.
        """
        if not self._app.packaged:
            return False

        async def preparing() -> None:
            self._phase = "preparing"
            await self._announce()

        try:
            return await self._app.check_and_prepare(preparing)
        except PrepareError as error:
            logger.warning("could not prepare a Nest update: %s", error)
            return False
        finally:
            self._phase = "checking"

    def _in_use(self, engine: str) -> bool:
        """An npm engine the user never installed is not followed."""
        fetched = {found.id for found in npm_engines()}
        return engine not in fetched or (self._engines_dir / engine).is_dir()

    async def _prepare_what_is_new(self) -> None:
        now = await asyncio.to_thread(self._setup.versions)
        latest = await self._latest()
        target = {
            engine: latest[engine]
            if self._in_use(engine) and is_newer(latest.get(engine, ""), version)
            else version
            for engine, version in now.packages.items()
        }
        if target == now.packages:
            return
        state, ready = await asyncio.to_thread(self._read)
        if ready is not None and ready.packages == target:
            return
        if target in state.refused:
            logger.info("the newest engines failed; waiting for newer ones")
            return
        if state.base_python is None or state.base_fingerprint is None:
            msg = "the daemon did not start through `nestd serve`"
            raise UpdaterUnavailableError(msg)
        self._phase = "preparing"
        await self._announce()
        environment = await self._builder.build(
            Plan(state.base_python, state.base_fingerprint, now, target)
        )
        logger.info("prepared environment %s", environment)
        async with self._lock:
            state = await asyncio.to_thread(self._files.load)
            stale = state.ready
            await asyncio.to_thread(
                self._files.save, state.model_copy(update={"ready": environment, "refused": []})
            )
        if stale is not None:
            await asyncio.to_thread(shutil.rmtree, self._root / stale, True)

    async def _latest(self) -> dict[str, str]:
        """Engine id to the newest version published; left out when that one was pulled."""
        async with httpx.AsyncClient(
            transport=self._setup.transport, timeout=REGISTRY_TIME_LIMIT
        ) as client:
            engines = followed_engines()
            found = await asyncio.gather(
                *(
                    latest_on_npm(client, engine.package)
                    if engine.on_npm
                    else latest_on_pypi(client, engine.package)
                    for engine in engines
                )
            )
        return {
            engine.id: version
            for engine, version in zip(engines, found, strict=True)
            if version is not None
        }

    async def _settle(self) -> None:
        try:
            running = running_environment(self._root, self._setup.prefix)
            state = await asyncio.to_thread(self._files.load)
            if running is not None and state.current == running:
                await self._confirm()
            await self._clear_unused()
        except Exception:
            # An unconfirmed boot ends with its watch; what was not cleared waits for a start.
            logger.exception("could not finish after the start")

    async def _confirm(self) -> None:
        # Polled: the answer is another process's, this one's own server seen from outside.
        while not await self._setup.healthy(self._port()):  # noqa: ASYNC110
            await asyncio.sleep(HEALTH_EVERY_SECONDS)
        async with self._lock:
            state = await asyncio.to_thread(self._files.load)
            await asyncio.to_thread(self._files.save, confirmed(state))
        if self.watch is not None:
            self.watch.confirm()
        logger.info("the daemon answered from its environment; the boot is confirmed")

    async def _clear_unused(self) -> None:
        async with self._lock:
            # A prepare under way has a half-made folder; the next start clears up.
            if self._task is not None:
                return
            state = await asyncio.to_thread(self._files.load)
            await asyncio.to_thread(self._clear, state)

    def _clear(self, state: UpdateState) -> None:
        running = running_environment(self._root, self._setup.prefix)
        keep = kept_folders(state) | ({running} if running is not None else set[str]())
        for name in remove_unused(self._root, keep):
            logger.info("removed environment %s", name)
        self._app.clear_unused()
        running_engines = {engine.id: engine.version for engine in ACP_ENGINES}
        for engine in BASE_ENGINES:
            folder = self._engines_dir / engine.id
            if engine.delivery == "bundled" and folder.is_dir():
                held = kept_versions(self._root, engine.id)
                remove_old(
                    folder, {*held, engine.version or "", running_engines.get(engine.id) or ""}
                )
