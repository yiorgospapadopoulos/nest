"""Preparing an environment beside the running one, which is never touched.

A venv with exactly what the base has, then the engines at their new versions; `uv` moves
anything else only when a new version requires it. The npm engines land in their own
version folders. The offline check then runs inside the new environment, and only when it
passes is the half-made folder renamed into place.
"""

import asyncio
import logging
import re
import shutil
import subprocess
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from pydantic import ValidationError

from nestd.engine.acp_install import (
    EnvSource,
    NpmError,
    NpmRunner,
    fetch_version,
    installed_program,
)
from nestd.updates.engines import Versions, changes, followed_engines, npm_engines, summary
from nestd.updates.environments import PARTIAL_SUFFIX, new_environment_id, python_of
from nestd.updates.manifest import Manifest, write_manifest
from nestd.updates.selfcheck_report import SelfcheckReport

logger = logging.getLogger(__name__)

# Runs uv with these arguments in a folder and environment; what it printed.
type UvRunner = Callable[[Sequence[str], Path, Mapping[str, str]], Awaitable[str]]
# The offline check inside an environment: its Python, the engines folder, a working folder
# and the environment to start from. Raises PrepareError when it cannot be read.
type SelfcheckRunner = Callable[[Path, Path, Path, Mapping[str, str]], Awaitable[SelfcheckReport]]

UV_TIME_LIMIT = 900.0
SELFCHECK_TIME_LIMIT = 300.0
REQUIREMENTS_NAME = "nest-requirements.txt"
_DETAIL_LIMIT = 500
_PINNED_NESTD = re.compile(r"nestd(==| @)")


class PrepareError(Exception):
    """The environment could not be made or failed its check; nothing was kept."""


class UpdaterUnavailableError(PrepareError):
    """This install cannot make environments: no uv, or Nest not installed from its source."""


async def _run(
    argv: Sequence[str], cwd: Path, env: Mapping[str, str], time_limit: float
) -> tuple[int, str, str]:
    """The exit code, stdout and stderr; killed on a timeout and with a cancelled caller."""
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(time_limit):
            stdout, stderr = await process.communicate()
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    return process.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def run_uv(args: Sequence[str], cwd: Path, env: Mapping[str, str]) -> str:
    uv = shutil.which("uv", path=env.get("PATH"))
    if uv is None:
        msg = "uv was not found"
        raise UpdaterUnavailableError(msg)
    try:
        code, stdout, stderr = await _run((uv, *args), cwd, env, UV_TIME_LIMIT)
    except (OSError, TimeoutError) as error:
        msg = f"uv {args[0]} could not finish ({type(error).__name__})"
        raise PrepareError(msg) from error
    if code != 0:
        msg = f"uv {' '.join(args[:2])} failed ({code}): {stderr[-_DETAIL_LIMIT:]}"
        raise PrepareError(msg)
    return stdout


async def run_selfcheck(
    python: Path, engines_dir: Path, cwd: Path, env: Mapping[str, str]
) -> SelfcheckReport:
    argv = (python, "-m", "nestd", "engines", "selfcheck", "--engines-dir", engines_dir)
    try:
        _, stdout, stderr = await _run([str(a) for a in argv], cwd, env, SELFCHECK_TIME_LIMIT)
    except (OSError, TimeoutError) as error:
        msg = f"the check could not finish ({type(error).__name__})"
        raise PrepareError(msg) from error
    lines = stdout.strip().splitlines()
    try:
        return SelfcheckReport.model_validate_json(lines[-1] if lines else "")
    except ValidationError as error:
        msg = f"the check printed no report: {stderr[-_DETAIL_LIMIT:]}"
        raise PrepareError(msg) from error


@dataclass(frozen=True)
class Plan:
    base_python: str
    base_fingerprint: str
    # What this process runs now, for what the update changes.
    now: Versions
    # Engine id to the package version the new environment gets, changed or not: the base
    # may have older ones than the environment running now.
    packages: Mapping[str, str]


class EnvironmentBuilder:
    def __init__(
        self,
        root: Path,
        engines_dir: Path,
        uv: UvRunner,
        npm: NpmRunner,
        selfcheck: SelfcheckRunner,
        env: EnvSource,
    ) -> None:
        """`root` is `<data_dir>/environments`; `env` is the daemon's environment with the
        login shell's over it, where uv, npm and node are found.
        """
        self._root = root
        self._engines_dir = engines_dir
        self._uv = uv
        self._npm = npm
        self._selfcheck = selfcheck
        self._env = env

    async def build(self, plan: Plan) -> str:
        """The new environment's id, in place and checked. Raises PrepareError with nothing
        left.
        """
        env = await self._env()
        await asyncio.to_thread(self._root.mkdir, parents=True, exist_ok=True)
        freeze = await self._uv(("pip", "freeze", "--python", plan.base_python), self._root, env)
        wheel = released_wheel(plan.base_python)
        if wheel is None and not _from_source(freeze):
            msg = "Nest is neither an editable install nor a released one"
            raise UpdaterUnavailableError(msg)
        environment = new_environment_id()
        partial = self._root / f"{environment}{PARTIAL_SUFFIX}"
        try:
            await self._fill(partial, freeze, wheel, plan, env)
            await asyncio.to_thread(partial.rename, self._root / environment)
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise
        return environment

    async def _fill(
        self, partial: Path, freeze: str, wheel: Path | None, plan: Plan, env: Mapping[str, str]
    ) -> None:
        python = python_of(partial)
        requirements = partial / REQUIREMENTS_NAME
        # Relocatable, since this folder is renamed once it passes.
        await self._uv(
            ("venv", "--relocatable", "--python", plan.base_python, str(partial)), self._root, env
        )
        try:
            frozen = freeze if wheel is None else _without_nestd(freeze)
            await asyncio.to_thread(requirements.write_text, frozen, encoding="utf-8")
            await self._uv(
                ("pip", "install", "--python", str(python), "--no-deps", "-r", str(requirements)),
                self._root,
                env,
            )
            if wheel is not None:
                await self._uv(
                    ("pip", "install", "--python", str(python), "--no-deps", str(wheel)),
                    self._root,
                    env,
                )
            await self._uv(
                ("pip", "install", "--python", str(python), "--only-binary", ":all:", *_pins(plan)),
                self._root,
                env,
            )
            await self._fetch_npm_engines(plan, env)
            manifest = Manifest(base_fingerprint=plan.base_fingerprint, packages=plan.packages)
            # Before the check, which reads the ACP versions from it.
            await asyncio.to_thread(write_manifest, partial, manifest)
            report = await self._selfcheck(python, self._engines_dir, self._root, env)
            if not report.ok:
                raise PrepareError(report.failure())
            await asyncio.to_thread(
                write_manifest, partial, _with_report(manifest, plan.now, report)
            )
        except (NpmError, OSError) as error:
            raise PrepareError(str(error) or type(error).__name__) from error

    async def _fetch_npm_engines(self, plan: Plan, env: Mapping[str, str]) -> None:
        """Only engines the user installed: the rest need npm, which a machine may not have."""
        for engine in npm_engines():
            folder = self._engines_dir / engine.id
            if not folder.is_dir():
                continue
            wanted = replace(engine, version=plan.packages.get(engine.id, engine.version))
            if installed_program(wanted, folder / (wanted.version or "")) is None:
                await fetch_version(wanted, folder, self._npm, env)


def _from_source(freeze: str) -> bool:
    lines = freeze.splitlines()
    return any(line.startswith("-e ") for line in lines) and not any(
        _PINNED_NESTD.match(line) for line in lines
    )


def released_wheel(base_python: str) -> Path | None:
    """The wheel a released base keeps in its folder; None for a checkout's base."""
    wheels = sorted(Path(base_python).parent.parent.glob("nestd-*.whl"))
    return wheels[-1] if wheels else None


def _without_nestd(freeze: str) -> str:
    """Otherwise uv would look for `nestd` on PyPI, where it is someone else's or nothing."""
    return "".join(
        line for line in freeze.splitlines(keepends=True) if not _PINNED_NESTD.match(line)
    )


def _pins(plan: Plan) -> list[str]:
    return [
        f"{engine.package}=={plan.packages[engine.id]}"
        for engine in followed_engines()
        if not engine.on_npm
    ]


def _with_report(manifest: Manifest, now: Versions, report: SelfcheckReport) -> Manifest:
    shown = {engine.id: engine.version for engine in report.engines if engine.version}
    moved = changes(now, manifest.packages, shown)
    return manifest.model_copy(update={"shown": shown, "summary": summary(moved)})
