"""Fetching the voice engine and its model into `<data_dir>/voice/` (B154).

The engine is a venv of its own, `engine-<fingerprint>/`, made with the daemon's Python and
filled by pip from `constraints.txt`, wheels only; the fingerprint follows that file and the
Python version, so new pins make a new one. A model is a folder in `models/<id>/`. Each is
made in a `.partial` folder and moved into place when whole, so a folder in place is always
complete; older engines and other models go once the new one is in place.
"""

import asyncio
import contextlib
import hashlib
import logging
import os
import shutil
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path

from nestd.voice.models import VoiceModel

logger = logging.getLogger(__name__)

CONSTRAINTS = Path(__file__).with_name("constraints.txt")
WORKER = Path(__file__).with_name("worker.py")
ENGINE_PACKAGE = "faster-whisper==1.2.1"
PARTIAL = ".partial"
_ENGINE_PREFIX = "engine-"
_COMPLETE = ".complete"
_MODEL_FILE = "model.bin"
# A slow network fetching about 90 MB of wheels, or a model up to 1.5 GB.
PACKAGES_TIME_LIMIT = 1200.0
MODEL_TIME_LIMIT = 3600.0
_DETAIL_LIMIT = 300
# Passed on to pip and the model download: reaching the network as the user does.
_KEPT_VARIABLES = (
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)


class VoiceInstallError(Exception):
    """A step failed or could not start; the message says why, in plain words."""


# Runs a command with this environment for at most this many seconds; what it printed.
# Raises VoiceInstallError.
type CommandRunner = Callable[[Sequence[str], Mapping[str, str], float], Awaitable[str]]


def worker_env(source: Mapping[str, str] = os.environ) -> dict[str, str]:
    env = {name: source[name] for name in _KEPT_VARIABLES if name in source}
    # No telemetry, and never the user's own Hugging Face token: the models are public.
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"  # noqa: S105 (a switch, not a secret)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


async def run_command(args: Sequence[str], env: Mapping[str, str], time_limit: float) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=dict(env),
        )
    except OSError as error:
        msg = f"could not start {Path(args[0]).name}: {error}"
        raise VoiceInstallError(msg) from error
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), time_limit)
    except TimeoutError as error:
        await _stop(process)
        msg = f"it took longer than {int(time_limit / 60)} minutes"
        raise VoiceInstallError(msg) from error
    except asyncio.CancelledError:
        # Stopped with the daemon: pip or the download must not go on writing.
        await asyncio.shield(_stop(process))
        raise
    if process.returncode != 0:
        said = stderr.decode(errors="replace").strip()[-_DETAIL_LIMIT:]
        msg = f"{Path(args[0]).name} failed ({process.returncode}): {said}"
        raise VoiceInstallError(msg)
    return stdout.decode(errors="replace")


async def _stop(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    await process.wait()


class VoiceFolder:
    """Where the engine, the models and recordings being turned into text live."""

    def __init__(self, root: Path, python_version: str = sys.version) -> None:
        self.root = root
        digest = hashlib.sha256(CONSTRAINTS.read_bytes())
        digest.update(ENGINE_PACKAGE.encode())
        digest.update(python_version.split()[0].encode())
        self.engine = root / f"{_ENGINE_PREFIX}{digest.hexdigest()[:12]}"
        self.models = root / "models"
        self.recordings = root / "recordings"

    @property
    def python(self) -> Path:
        return self.engine / "bin" / "python"

    def engine_ready(self) -> bool:
        return (self.engine / _COMPLETE).is_file() and self.python.exists()

    def model_dir(self, model: VoiceModel) -> Path:
        return self.models / model.id

    def model_ready(self, model: VoiceModel) -> bool:
        return (self.model_dir(model) / _MODEL_FILE).is_file()

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


async def install_engine(folder: VoiceFolder, python: Path, run: CommandRunner) -> None:
    """A venv with the pinned packages, whole or not at all."""
    partial = folder.engine.with_name(folder.engine.name + PARTIAL)
    await asyncio.to_thread(shutil.rmtree, partial, True)
    folder.root.mkdir(parents=True, exist_ok=True)
    env = worker_env()
    await run((str(python), "-I", "-m", "venv", str(partial)), env, PACKAGES_TIME_LIMIT)
    await run(
        (
            str(partial / "bin" / "python"),
            "-I",
            "-m",
            "pip",
            "install",
            # Not the user's pip.conf or PIP_ variables: only what is pinned here.
            "--isolated",
            "--no-input",
            "--no-cache-dir",
            "--only-binary=:all:",
            "--constraint",
            str(CONSTRAINTS),
            ENGINE_PACKAGE,
        ),
        env,
        PACKAGES_TIME_LIMIT,
    )
    (partial / _COMPLETE).touch()
    await asyncio.to_thread(_replace, partial, folder.engine)
    await asyncio.to_thread(_remove_other_engines, folder)


async def install_model(folder: VoiceFolder, model: VoiceModel, run: CommandRunner) -> None:
    """The model's files, whole or not at all; other models go once it is in place."""
    target = folder.model_dir(model)
    partial = target.with_name(target.name + PARTIAL)
    await asyncio.to_thread(shutil.rmtree, partial, True)
    folder.models.mkdir(parents=True, exist_ok=True)
    await run(
        (
            str(folder.python),
            "-I",
            str(WORKER),
            "download",
            "--model",
            model.id,
            "--revision",
            model.revision,
            "--into",
            str(partial),
        ),
        worker_env(),
        MODEL_TIME_LIMIT,
    )
    if not (partial / _MODEL_FILE).is_file():
        msg = f"the {model.label} model came without its {_MODEL_FILE}"
        raise VoiceInstallError(msg)
    await asyncio.to_thread(_replace, partial, target)
    await asyncio.to_thread(_remove_other_models, folder, model)


def _replace(partial: Path, target: Path) -> None:
    shutil.rmtree(target, ignore_errors=True)
    partial.rename(target)


def _remove_other_engines(folder: VoiceFolder) -> None:
    for entry in folder.root.iterdir():
        if entry.name.startswith(_ENGINE_PREFIX) and entry != folder.engine:
            logger.info("removing the old voice engine %s", entry.name)
            shutil.rmtree(entry, ignore_errors=True)


def _remove_other_models(folder: VoiceFolder, kept: VoiceModel) -> None:
    for entry in folder.models.iterdir():
        if entry.name != kept.id:
            shutil.rmtree(entry, ignore_errors=True)
