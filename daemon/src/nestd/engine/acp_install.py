"""Where each ACP engine's program is, and fetching the pinned ones into Nest's folder (B107).

A pinned engine lives in `<data_dir>/engines/<id>/<version>/`, an npm prefix made with
`npm install --ignore-scripts`, never a global install: no package script runs. It is
installed into a hidden folder first and moved into place when its program is there, so a
version folder is always whole; older versions go once the pinned one is in place, except
those a prepared environment holds (`nestd/updates`). An engine the user installs
themselves (`user_install`) is looked for on the login shell's PATH and where its
installer puts it.

The state is worked out from the folders each time, so a restart forgets nothing but why
the last install failed.
"""

import asyncio
import logging
import platform
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from nestd.errors import ConflictError
from nestd.providers.acp_engines import AcpEngine
from nestd.updates.environments import kept_versions

logger = logging.getLogger(__name__)

type EngineState = Literal["ready", "not_installed", "installing", "install_failed"]
# Runs npm with these arguments in a folder and environment; raises NpmError when it fails.
type NpmRunner = Callable[[Sequence[str], Path, Mapping[str, str]], Awaitable[None]]
# The environment engines and npm start from: the daemon's with the login shell's over it.
type EnvSource = Callable[[], Awaitable[Mapping[str, str]]]

# The scratch folder model lists are read in, beside the versions (never removed with them).
PROBE_FOLDER = "probe"
# A download of a large engine on a slow network.
NPM_TIME_LIMIT = 900.0
# What a failed npm says is cut to this, for Settings.
_DETAIL_LIMIT = 300
# Packages whose `.bin` entry is a placeholder their install script replaces: their real
# program is in the platform package npm installs beside them, by these names in order.
_NATIVE: Mapping[str, Callable[[str, str], tuple[str, ...]]] = {
    "opencode-ai": lambda os_name, arch: (
        f"opencode-{os_name}-{arch}",
        f"opencode-{os_name}-{arch}-baseline",
    ),
}
_OS = {"darwin": "darwin", "linux": "linux"}
_ARCH = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}


class NpmError(Exception):
    """npm failed or could not start; the message says why, in plain words."""


class EngineNotInstallableError(ConflictError):
    """Nest does not fetch this engine: the user installs it, or it is not supported."""


@dataclass(frozen=True)
class InstallState:
    state: EngineState
    # The installed version; None when not installed, or not known for the user's own.
    version: str | None = None
    # Why it is not supported, or why the last install failed, in plain words.
    detail: str | None = None
    program: Path | None = None


async def run_npm(args: Sequence[str], cwd: Path, env: Mapping[str, str]) -> None:
    """npm, found on the environment's PATH (it comes with Node)."""
    npm = shutil.which("npm", path=env.get("PATH"))
    if npm is None:
        msg = "npm was not found. Install Node.js, then try again."
        raise NpmError(msg)
    try:
        process = await asyncio.create_subprocess_exec(
            npm,
            *args,
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        msg = f"npm could not start ({type(error).__name__})"
        raise NpmError(msg) from error
    try:
        async with asyncio.timeout(NPM_TIME_LIMIT):
            _, stderr = await process.communicate()
    except TimeoutError as error:
        process.kill()
        await process.wait()
        msg = "npm took too long"
        raise NpmError(msg) from error
    if process.returncode != 0:
        lines = [line for line in stderr.decode(errors="replace").splitlines() if line.strip()]
        msg = f"npm failed ({process.returncode}): {' '.join(lines[-3:])}"[:_DETAIL_LIMIT]
        raise NpmError(msg)


def platform_names() -> tuple[str, str]:
    """This machine's system and processor as npm's platform packages name them."""
    return _OS.get(sys.platform, sys.platform), _ARCH.get(platform.machine(), platform.machine())


def installed_program(
    engine: AcpEngine, folder: Path, names: tuple[str, str] | None = None
) -> Path | None:
    """The engine's program inside an npm prefix, if it is there."""
    modules = folder / "node_modules"
    native = _NATIVE.get(engine.package or "")
    if native is not None:
        candidates = [
            modules / name / "bin" / engine.executable
            for name in native(*(names or platform_names()))
        ]
    else:
        candidates = [modules / ".bin" / engine.executable]
    return next((path for path in candidates if path.is_file()), None)


class EngineInstall:
    def __init__(
        self,
        engine: AcpEngine,
        root: Path,
        npm: NpmRunner,
        env: EnvSource,
        home: Path,
        on_change: Callable[[InstallState], Awaitable[None]] | None = None,
        environments: Path | None = None,
    ) -> None:
        """`root` is `<data_dir>/engines`; `home` is the user's home, which expands their own
        install paths;
        `on_change` hears each state an install goes through; the versions the environments
        in `environments` hold stay when older ones are cleared.
        """
        self.engine = engine
        self.folder = root / engine.id
        self._npm = npm
        self._env = env
        self.home = home
        self._on_change = on_change
        self._environments = environments
        self._task: asyncio.Task[InstallState] | None = None
        self._failure: str | None = None

    @property
    def fetched(self) -> bool:
        """Nest fetches it from npm, so it can be installed from Settings."""
        return self.engine.delivery == "bundled"

    async def current(self) -> InstallState:
        engine = self.engine
        if engine.delivery == "user_install":
            program = await self._user_program()
            if program is None:
                detail = f"Install {engine.name} yourself; Nest uses it from your PATH."
                return InstallState("not_installed", detail=detail)
            return InstallState("ready", program=program)
        if self._task is not None:
            return InstallState("installing")
        program = self._pinned_program()
        if program is not None:
            return InstallState("ready", version=engine.version, program=program)
        if self._failure is not None:
            return InstallState("install_failed", detail=self._failure)
        return InstallState("not_installed")

    def start(self) -> bool:
        """Install it in the background unless it is there or being installed; whether an
        install runs now.
        """
        if not self.fetched:
            return False
        if self._task is not None:
            return True
        if self._pinned_program() is not None:
            return False
        self._task = asyncio.create_task(self._install())
        return True

    async def install(self) -> InstallState:
        """Install it now unless it is there, waiting until it is done; 409 for an engine
        Nest does not fetch.
        """
        if not self.fetched:
            msg = f"Nest does not install {self.engine.name}"
            raise EngineNotInstallableError(msg)
        self.start()
        task = self._task
        if task is not None:
            return await asyncio.shield(task)
        return await self.current()

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _pinned_program(self) -> Path | None:
        if self.engine.version is None:
            return None
        return installed_program(self.engine, self.folder / self.engine.version)

    async def _user_program(self) -> Path | None:
        env = await self._env()
        found = shutil.which(self.engine.executable, path=env.get("PATH", ""))
        if found is not None:
            return Path(found)
        for raw in self.engine.user_paths:
            path = Path(raw.replace("~", str(self.home), 1)) if raw.startswith("~") else Path(raw)
            if path.is_file():
                return path
        return None

    async def _install(self) -> InstallState:
        engine = self.engine
        version = engine.version
        assert version is not None  # noqa: S101 (a fetched engine's)
        self._failure = None
        await self._announce(InstallState("installing"))
        try:
            await fetch_version(engine, self.folder, self._npm, await self._env())
        except (NpmError, OSError) as error:
            self._failure = str(error) or type(error).__name__
            logger.warning("could not install %s %s: %s", engine.id, version, self._failure)
            state = InstallState("install_failed", detail=self._failure)
        else:
            await asyncio.to_thread(self._clear_old, version)
            logger.info("installed %s %s", engine.id, version)
            state = InstallState("ready", version=version, program=self._pinned_program())
        finally:
            self._task = None
        await self._announce(state)
        return state

    def _clear_old(self, version: str) -> None:
        keep = {version}
        if self._environments is not None:
            keep |= kept_versions(self._environments, self.engine.id)
        remove_old(self.folder, keep)

    async def _announce(self, state: InstallState) -> None:
        if self._on_change is not None:
            await self._on_change(state)


async def fetch_version(
    engine: AcpEngine, folder: Path, npm: NpmRunner, env: Mapping[str, str]
) -> None:
    """`engine.version` into `folder/<version>/`, whole or not at all; other versions stay.
    Raises NpmError or OSError.
    """
    version = engine.version
    assert engine.package is not None  # noqa: S101 (a fetched engine's)
    assert version is not None  # noqa: S101 (a fetched engine's)
    target = folder / version
    partial = folder / f".{version}.partial"
    try:
        await asyncio.to_thread(_fresh_folder, partial)
        await npm(
            (
                "install",
                "--prefix",
                str(partial),
                "--no-fund",
                "--no-audit",
                "--ignore-scripts",
                f"{engine.package}@{version}",
            ),
            partial,
            env,
        )
        if installed_program(engine, partial) is None:
            msg = f"{engine.name}'s program was not found after installing it"
            raise NpmError(msg)
        await asyncio.to_thread(_move_into_place, partial, target)
    except (NpmError, OSError):
        await asyncio.to_thread(shutil.rmtree, partial, True)
        raise


def _fresh_folder(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)


def _move_into_place(partial: Path, target: Path) -> None:
    shutil.rmtree(target, ignore_errors=True)
    partial.rename(target)


def remove_old(folder: Path, keep: Collection[str]) -> None:
    """Every version folder not in `keep`; the probe folder, Nest's files beside them and
    an install in progress stay.
    """
    for entry in folder.iterdir():
        if (
            entry.is_dir()
            and not entry.is_symlink()
            and not entry.name.startswith(".")
            and entry.name != PROBE_FOLDER
            and entry.name not in keep
        ):
            shutil.rmtree(entry, ignore_errors=True)
