"""Updating Nest itself on a released install (B130): `<data>/daemon/<version>/` beside the
running one, and the `current` link the service starts.

A check fetches `latest.json`. A newer release is downloaded, checked against its sha256,
built and run through `engines selfcheck` before anything shows, and the running daemon is
never touched. Relaunch backs up the database, starts `watcher.py`, moves `current` and ends
the daemon, so the service starts the new one. `watcher.py` undoes all of it if the new one
does not answer. An app compares its own version with `app_file` once the daemon is back and
swaps itself: a daemon that answers with the new version is by then a healthy one.

A checkout never gets here: `packaged` is False, so the user's own Nest is untouched.
"""

import asyncio
import hashlib
import logging
import platform as python_platform
import re
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, ValidationError

from nestd import __version__
from nestd.errors import ConflictError
from nestd.paths import AppPaths
from nestd.platform import PlatformName
from nestd.release import release_url
from nestd.updates.build import PrepareError, SelfcheckRunner, UvRunner
from nestd.updates.state import write_atomically
from nestd.updates.versions import is_newer

logger = logging.getLogger(__name__)

STATE_NAME = "update.json"
CURRENT = "current"
# The app's own download, kept in each version's folder for the app to swap to, also on Undo.
APP_FILE = "app-file"
BACKUPS = "backups-update"
PARTIAL_SUFFIX = ".partial"
TIME_LIMIT = 900.0
_VERSION = re.compile(r"\d+(?:\.\d+)*")
_MACHINES = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64"}


class ReleaseFile(BaseModel):
    platform: str
    kind: str
    name: str
    sha256: str


class Release(BaseModel):
    version: str
    notes: str = ""
    files: list[ReleaseFile]

    def file(self, kind: str, platform: str) -> ReleaseFile:
        for entry in self.files:
            if entry.kind == kind and entry.platform == platform:
                return entry
        msg = f"the release has no {kind} for {platform}"
        raise PrepareError(msg)


class AppUpdate(BaseModel):
    """What Relaunch would install."""

    version: str
    notes: str


class AppFile(BaseModel):
    """The app that belongs to the running daemon. An app of another version swaps to it."""

    version: str
    path: str


class Updating(BaseModel):
    """A relaunch under way, for the apps to show while the daemon is down: they read this
    file themselves then. The watcher clears it once the new version answers or is undone.
    """

    from_version: str
    to_version: str
    started_at: str


class AppState(BaseModel):
    ready: AppUpdate | None = None
    updating: Updating | None = None
    # What Undo returns to, and the database version it can run on.
    previous: str | None = None
    previous_schema: int | None = None
    # Versions that failed to start, not offered again.
    refused: list[str] = []
    notice: str | None = None


def apple_tools_installed() -> bool:
    try:
        done = subprocess.run(
            ["/usr/bin/xcode-select", "-p"], capture_output=True, check=False, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def without_apple_stubs(
    env: Mapping[str, str], installed: Callable[[], bool] = apple_tools_installed
) -> dict[str, str]:
    """On a Mac without Apple's developer tools, `install_name_tool` in /usr/bin is a stand-in
    that opens Apple's install window, and uv runs it after fetching Python for a rename it
    does without. So uv gets only its own folder on the PATH there (see `install.sh`).
    """
    uv = shutil.which("uv", path=env.get("PATH"))
    if sys.platform != "darwin" or uv is None or installed():
        return dict(env)
    return {**env, "PATH": str(Path(uv).parent)}


def platform_key(name: PlatformName, machine: str | None = None) -> str:
    """The release's name for this machine, such as `macos-arm64`."""
    return f"{name}-{_MACHINES.get(machine or python_platform.machine(), 'unsupported')}"


def read_state(daemon_dir: Path) -> AppState:
    try:
        return AppState.model_validate_json((daemon_dir / STATE_NAME).read_bytes())
    except (OSError, ValidationError):
        return AppState()


def save_state(daemon_dir: Path, state: AppState) -> None:
    write_atomically(daemon_dir / STATE_NAME, state.model_dump_json())


STARTS_NAME = "starts"


def note_start(daemon_dir: Path, version: str) -> None:
    """One line for each time this version's daemon starts, so the watcher can tell a
    crashing one from a slow one. Best effort: a start never fails over it.
    """
    folder = daemon_dir / version
    if not folder.is_dir():
        return
    try:
        with (folder / STARTS_NAME).open("a", encoding="utf-8") as file:
            file.write("start\n")
    except OSError:
        logger.warning("could not note this start of %s", version)


def starts_of(daemon_dir: Path, version: str) -> int:
    try:
        return len((daemon_dir / version / STARTS_NAME).read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0


def point_current(daemon_dir: Path, version: str) -> None:
    """Moves the link in one step, so the service always finds a whole version."""
    new = daemon_dir / f".{CURRENT}.new"
    new.unlink(missing_ok=True)
    new.symlink_to(version)
    new.replace(daemon_dir / CURRENT)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def database_version(database: Path) -> int:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5.0)
    try:
        row = connection.execute("PRAGMA user_version").fetchone()
    finally:
        connection.close()
    return int(row[0]) if row is not None else 0


def back_up_database(database: Path, backup: Path) -> None:
    """A whole copy through SQLite, WAL included, proved readable before it is relied on."""
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.unlink(missing_ok=True)
    source = sqlite3.connect(database, timeout=5.0)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
        row = target.execute("PRAGMA integrity_check").fetchone()
    finally:
        target.close()
        source.close()
    if row is None or row[0] != "ok":
        backup.unlink(missing_ok=True)
        msg = "the database backup failed its check, so the update did not start"
        raise ConflictError(msg)


def start_watcher(daemon_dir: Path, port: int, old: str, new: str, backup: Path) -> None:
    """In a session of its own, from the old version's folder: launchd ends a job's leftover
    processes, and `current` is about to move.
    """
    python = daemon_dir / old / "bin" / "python"
    subprocess.Popen(  # noqa: S603 (Nest's own folder, a fixed command)
        [str(python), "-m", "nestd.updates.watcher", str(port), old, new, str(backup)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


type EnvSource = Callable[[], Awaitable[Mapping[str, str]]]
type StartWatcher = Callable[[Path, int, str, str, Path], None]


class AppUpdater:
    def __init__(
        self,
        *,
        paths: AppPaths,
        platform: PlatformName,
        packaged: bool,
        uv: UvRunner,
        selfcheck: SelfcheckRunner,
        env: EnvSource,
        transport: httpx.AsyncBaseTransport | None = None,
        running: str = __version__,
        watcher: StartWatcher = start_watcher,
    ) -> None:
        self._paths = paths
        self._daemon_dir = paths.daemon_dir
        self._platform = platform_key(platform)
        self._packaged = packaged
        self._uv = uv
        self._selfcheck = selfcheck
        self._env = env
        self._transport = transport
        self._running = running
        self._watcher = watcher

    @property
    def packaged(self) -> bool:
        return self._packaged

    def state(self) -> AppState:
        return read_state(self._daemon_dir) if self._packaged else AppState()

    def app_file(self) -> AppFile | None:
        path = self._daemon_dir / self._running / APP_FILE
        if not self._packaged or not path.is_file():
            return None
        return AppFile(version=self._running, path=str(path))

    def can_undo(self) -> bool:
        state = self.state()
        if state.previous is None or state.previous_schema is None:
            return False
        try:
            return database_version(self._paths.db_path) == state.previous_schema
        except sqlite3.Error:
            return False

    def dismiss(self) -> None:
        state = self.state()
        if state.notice is not None:
            save_state(self._daemon_dir, state.model_copy(update={"notice": None}))

    async def check_and_prepare(self, preparing: Callable[[], Awaitable[None]]) -> bool:
        """Prepare a newer release if there is one; whether one is ready. Nothing changes
        unless the whole of it downloads, installs and passes its check. `preparing` is
        called once there is one to prepare.
        """
        if not self._packaged:
            return False
        state = await asyncio.to_thread(self.state)
        release = await self._latest()
        new = release.version
        if not is_newer(new, self._running) or new in state.refused:
            return False
        if state.ready is not None and state.ready.version == new:
            return True
        await preparing()
        await self._prepare(release)
        state = await asyncio.to_thread(self.state)
        update = AppUpdate(version=new, notes=release.notes)
        await asyncio.to_thread(
            save_state, self._daemon_dir, state.model_copy(update={"ready": update})
        )
        return True

    async def relaunch(self, port: int) -> None:
        """Everything up to ending the daemon, which the caller does next."""
        state = await asyncio.to_thread(self.state)
        if state.ready is None:
            msg = "No update is ready"
            raise ConflictError(msg)
        new = state.ready.version
        backup = self._paths.data_dir / BACKUPS / f"nest.db.before-{new}"
        database = self._paths.db_path
        await asyncio.to_thread(back_up_database, database, backup)
        schema = await asyncio.to_thread(database_version, database)
        await asyncio.to_thread(self._watcher, self._daemon_dir, port, self._running, new, backup)
        updating = Updating(
            from_version=self._running, to_version=new, started_at=datetime.now(UTC).isoformat()
        )
        (self._daemon_dir / new / STARTS_NAME).unlink(missing_ok=True)
        update = {
            "ready": None,
            "previous": self._running,
            "previous_schema": schema,
            "updating": updating,
        }
        await asyncio.to_thread(save_state, self._daemon_dir, state.model_copy(update=update))
        await asyncio.to_thread(point_current, self._daemon_dir, new)

    async def undo(self) -> None:
        """Back to the previous version, whose code reads this database; the caller then ends
        the daemon. An update that changed the database cannot be undone: `can_undo` says so.
        """
        state = await asyncio.to_thread(self.state)
        if state.previous is None or not await asyncio.to_thread(self.can_undo):
            msg = "There is nothing to go back to"
            raise ConflictError(msg)
        await asyncio.to_thread(point_current, self._daemon_dir, state.previous)
        update = {"previous": None, "previous_schema": None}
        await asyncio.to_thread(save_state, self._daemon_dir, state.model_copy(update=update))

    def clear_unused(self) -> None:
        """Only the running version, the one to go back to and the one ready are kept."""
        if not self._packaged or not self._daemon_dir.is_dir():
            return
        state = self.state()
        keep = {self._running, state.previous, state.ready.version if state.ready else None}
        for entry in self._daemon_dir.iterdir():
            name = entry.name.removesuffix(PARTIAL_SUFFIX)
            removable = entry.is_dir() and not entry.is_symlink() and _VERSION.fullmatch(name)
            if removable and (entry.name not in keep or entry.name != name):
                shutil.rmtree(entry, ignore_errors=True)

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport, timeout=TIME_LIMIT, follow_redirects=True
        )

    async def _address(self, name: str) -> str:
        return f"{release_url(await self._env())}/{name}"

    async def _latest(self) -> Release:
        address = await self._address("latest.json")
        async with await self._client() as client:
            try:
                response = await client.get(address)
                response.raise_for_status()
            except httpx.HTTPError as error:
                msg = f"could not read {address}: {error}"
                raise PrepareError(msg) from error
        try:
            return Release.model_validate_json(response.content)
        except ValidationError as error:
            msg = f"could not read {address}"
            raise PrepareError(msg) from error

    async def _download(self, entry: ReleaseFile, target: Path) -> None:
        address = await self._address(entry.name)
        async with await self._client() as client:
            try:
                async with client.stream("GET", address) as response:
                    response.raise_for_status()
                    with target.open("wb") as file:
                        async for chunk in response.aiter_bytes():
                            file.write(chunk)
            except httpx.HTTPError as error:
                msg = f"could not download {entry.name}: {error}"
                raise PrepareError(msg) from error
        if await asyncio.to_thread(sha256_of, target) != entry.sha256:
            await asyncio.to_thread(target.unlink, missing_ok=True)
            msg = f"{entry.name} did not match its sha256"
            raise PrepareError(msg)

    async def _prepare(self, release: Release) -> None:
        folder = self._daemon_dir / release.version
        partial = folder.with_name(folder.name + PARTIAL_SUFFIX)
        shutil.rmtree(partial, ignore_errors=True)
        try:
            await self._fill(partial, release)
            shutil.rmtree(folder, ignore_errors=True)
            await asyncio.to_thread(partial.rename, folder)
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise

    async def _fill(self, partial: Path, release: Release) -> None:
        wheel = release.file("wheel", "any")
        requirements = release.file("requirements", "any")
        app = release.file("app", self._platform)
        env = await asyncio.to_thread(
            without_apple_stubs,
            {**await self._env(), "UV_PYTHON_INSTALL_DIR": str(self._paths.bin_dir / "python")},
        )
        await asyncio.to_thread(self._daemon_dir.mkdir, parents=True, exist_ok=True)
        python = str(partial / "bin" / "python")
        cwd = self._daemon_dir
        await self._uv(
            (
                "venv",
                "--relocatable",
                "--python",
                "3.12",
                "--python-preference",
                "only-managed",
                str(partial),
            ),
            cwd,
            env,
        )
        try:
            await self._download(wheel, partial / wheel.name)
            await self._download(requirements, partial / "requirements.txt")
            await self._download(app, partial / APP_FILE)
        except OSError as error:
            raise PrepareError(str(error) or type(error).__name__) from error
        requirement_file = str(partial / "requirements.txt")
        await self._uv(
            ("pip", "install", "--python", python, "--require-hashes", "-r", requirement_file),
            cwd,
            env,
        )
        await self._uv(
            ("pip", "install", "--python", python, "--no-deps", str(partial / wheel.name)),
            cwd,
            env,
        )
        report = await self._selfcheck(Path(python), self._paths.engines_dir, cwd, env)
        if not report.ok:
            raise PrepareError(report.failure())
        logger.info("prepared Nest %s", release.version)
