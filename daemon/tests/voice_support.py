"""Voice input without pip, the network or Whisper (B154): a runner that makes what each
install step would, and workers that answer from a script."""

import io
import wave
from collections.abc import Mapping, Sequence
from pathlib import Path

from nestd.config.models import VoiceSettings
from nestd.platform.base import PlatformName
from nestd.voice.audio import SAMPLE_RATE
from nestd.voice.install import VoiceInstallError
from nestd.voice.process import VoiceWorkerError, Worker
from nestd.voice.service import VoiceService, VoiceSetup


def recording(seconds: float = 1.0, rate: int = SAMPLE_RATE, channels: int = 1) -> bytes:
    data = io.BytesIO()
    with wave.open(data, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\0\0" * channels * int(seconds * rate))
    return data.getvalue()


class FakeInstallRunner:
    """Makes the venv's Python and the model's file as the real steps would; `fail` makes
    the step whose command holds that word fail."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.fail: str | None = None

    async def __call__(self, args: Sequence[str], env: Mapping[str, str], _limit: float) -> str:
        self.commands.append(list(args))
        if self.fail is not None and self.fail in args:
            msg = f"{self.fail} failed"
            raise VoiceInstallError(msg)
        _make(args)
        return ""


def _make(args: Sequence[str]) -> None:
    if "venv" in args:
        python = Path(args[-1]) / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.touch()
    if "download" in args:
        into = Path(args[args.index("--into") + 1])
        into.mkdir(parents=True)
        (into / "model.bin").write_bytes(b"weights")


class FakeWorker:
    def __init__(self, model_dir: Path, answers: list[str | VoiceWorkerError]) -> None:
        self.model_dir = model_dir
        self._answers = answers
        self.heard: list[bytes] = []
        self.closed = False

    @property
    def alive(self) -> bool:
        return not self.closed

    async def transcribe(self, recording: Path, time_limit: float) -> str:
        self.heard.append(_read(recording))
        answer = self._answers.pop(0)
        if isinstance(answer, VoiceWorkerError):
            self.closed = True
            raise answer
        return answer

    async def close(self) -> None:
        self.closed = True


def _read(path: Path) -> bytes:
    return path.read_bytes()


class FakeWorkers:
    """Starts FakeWorkers that give `answers` in turn."""

    def __init__(self) -> None:
        self.answers: list[str | VoiceWorkerError] = []
        self.started: list[FakeWorker] = []

    async def __call__(self, _python: Path, model_dir: Path) -> Worker:
        worker = FakeWorker(model_dir, self.answers)
        self.started.append(worker)
        return worker


def fake_voice(
    root: Path,
    settings: VoiceSettings | None = None,
    platform: PlatformName = "macos",
) -> tuple[VoiceService, FakeInstallRunner, FakeWorkers]:
    runner = FakeInstallRunner()
    workers = FakeWorkers()
    chosen = settings or VoiceSettings()
    service = VoiceService(root, platform, lambda: chosen, VoiceSetup(runner, workers))
    return service, runner, workers
