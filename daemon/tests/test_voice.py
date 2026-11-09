"""Voice input (B154): what recordings it takes, fetching it whole or not at all, and a
worker that fails without leaving voice input broken."""

import asyncio
import sys
from pathlib import Path

import pytest

from nestd.config.models import VoiceSettings
from nestd.errors import ConflictError, InvalidInputError
from nestd.voice.audio import MAX_SECONDS, recording_seconds
from nestd.voice.process import ProcessWorker, VoiceWorkerError
from nestd.voice.service import VoiceFailedError, VoiceNotReadyError, VoiceService, VoiceSetup
from tests.async_support import until
from tests.voice_support import FakeInstallRunner, fake_voice, recording


def test_a_recording_must_be_16_khz_mono_pcm() -> None:
    assert recording_seconds(recording(2.5)) == 2.5
    for wrong in (recording(rate=44_100), recording(channels=2), b"not audio"):
        with pytest.raises(InvalidInputError):
            recording_seconds(wrong)


def test_a_recording_past_the_limit_is_refused_before_it_is_read() -> None:
    with pytest.raises(InvalidInputError, match="at most"):
        recording_seconds(recording(MAX_SECONDS + 1))


async def installed(service: VoiceService) -> None:
    service.start_install()
    await until(lambda: service.status().state != "installing")


async def test_it_fetches_the_engine_then_the_default_model(tmp_path: Path) -> None:
    service, runner, _ = fake_voice(tmp_path / "voice")
    before = service.status()
    assert (before.state, before.model) == ("not_installed", "small.en")
    assert before.download_mb > 0

    await installed(service)

    status = service.status()
    assert (status.state, status.download_mb) == ("ready", 0)
    steps = [
        next(word for word in ("venv", "pip", "download") if word in c) for c in runner.commands
    ]
    assert steps == ["venv", "pip", "download"]
    # Only wheels from the pinned list: no package runs its own build.
    pip = runner.commands[1]
    assert "--only-binary=:all:" in pip
    assert "--constraint" in pip


async def test_linux_defaults_to_the_smaller_model(tmp_path: Path) -> None:
    service, _, _ = fake_voice(tmp_path / "voice", platform="linux")

    assert service.status().model == "base.en"


async def test_a_failed_fetch_says_why_and_leaves_nothing_half_made(tmp_path: Path) -> None:
    service, runner, _ = fake_voice(tmp_path / "voice")
    runner.fail = "pip"

    await installed(service)

    status = service.status()
    assert status.state == "install_failed"
    assert status.detail == "pip failed"
    assert not service.folder.engine.exists()
    runner.fail = None
    await installed(service)
    assert service.status().state == "ready"


async def test_a_new_model_choice_fetches_only_the_model(tmp_path: Path) -> None:
    settings = VoiceSettings()
    runner = FakeInstallRunner()
    service = VoiceService(tmp_path / "voice", "macos", lambda: settings, VoiceSetup(run=runner))
    await installed(service)
    old_model = service.folder.model_dir(service.model())

    settings = VoiceSettings(model="tiny.en")
    await service.model_changed()
    assert service.status().state == "not_installed"
    runner.commands.clear()
    await installed(service)

    assert [c for c in runner.commands if "venv" in c or "pip" in c] == []
    assert service.status().state == "ready"
    # The model it replaced is deleted, as it is not used any more.
    assert not old_model.exists()


async def test_recordings_wait_for_the_download(tmp_path: Path) -> None:
    service, _, _ = fake_voice(tmp_path / "voice")

    with pytest.raises(VoiceNotReadyError):
        await service.transcribe(recording())


async def test_it_turns_a_recording_into_text_and_keeps_no_copy(tmp_path: Path) -> None:
    service, _, workers = fake_voice(tmp_path / "voice")
    await installed(service)
    workers.answers = ["run the tests", "and open a pull request"]
    sound = recording()

    assert await service.transcribe(sound) == "run the tests"
    assert await service.transcribe(sound) == "and open a pull request"

    # One worker for both, with the chosen model; the recording it heard is deleted.
    assert len(workers.started) == 1
    assert workers.started[0].model_dir == service.folder.model_dir(service.model())
    assert workers.started[0].heard == [sound, sound]
    assert list(service.folder.recordings.iterdir()) == []
    await service.close()
    assert workers.started[0].closed


async def test_a_worker_that_fails_is_replaced_on_the_next_recording(tmp_path: Path) -> None:
    service, _, workers = fake_voice(tmp_path / "voice")
    await installed(service)
    workers.answers = [VoiceWorkerError("the voice worker stopped"), "hello"]

    with pytest.raises(VoiceFailedError, match="stopped"):
        await service.transcribe(recording())
    assert await service.transcribe(recording()) == "hello"

    assert len(workers.started) == 2
    await service.close()


async def test_remove_deletes_the_download(tmp_path: Path) -> None:
    service, _, workers = fake_voice(tmp_path / "voice")
    await installed(service)
    workers.answers = ["hi"]
    await service.transcribe(recording())

    status = await service.remove()

    assert status.state == "not_installed"
    assert not service.folder.root.exists()
    assert workers.started[0].closed


def test_a_header_claiming_more_than_the_body_counts_only_the_body() -> None:
    sound = bytearray(recording(1.0))
    sound[40:44] = (2**32 - 1).to_bytes(4, "little")  # the data chunk's size

    assert recording_seconds(bytes(sound)) <= 1.0


async def test_a_tap_too_short_for_speech_is_nothing_heard(tmp_path: Path) -> None:
    service, _, workers = fake_voice(tmp_path / "voice")
    await installed(service)

    assert await service.transcribe(recording(0.05)) == ""
    assert workers.started == []


async def test_the_model_cannot_change_while_one_downloads(tmp_path: Path) -> None:
    service, _, _ = fake_voice(tmp_path / "voice")
    service.start_install()

    with pytest.raises(ConflictError):
        service.check_model_change()
    await until(lambda: service.status().state == "ready")
    service.check_model_change()


# Answers like worker.py: ready, then one line per request; "slow" waits before answering.
_STAND_IN = """
import json, sys, time
print(json.dumps({"ready": True}), flush=True)
for line in sys.stdin:
    path = json.loads(line)["path"]
    if "slow" in path:
        time.sleep(5)
    print(json.dumps({"text": "heard " + path}), flush=True)
"""


async def stand_in(tmp_path: Path) -> ProcessWorker:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _STAND_IN,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    worker = ProcessWorker(process, tmp_path / "worker.log")
    await worker.ready()
    return worker


async def test_a_real_worker_process_answers_each_recording(tmp_path: Path) -> None:
    worker = await stand_in(tmp_path)

    assert await worker.transcribe(Path("one.wav"), 10) == "heard one.wav"
    assert await worker.transcribe(Path("two.wav"), 10) == "heard two.wav"
    await worker.close()
    assert not worker.alive


async def test_a_worker_that_answers_late_is_stopped_not_reused(tmp_path: Path) -> None:
    worker = await stand_in(tmp_path)

    # Its late answer would otherwise be the next recording's text.
    with pytest.raises(VoiceWorkerError, match="no answer"):
        await worker.transcribe(Path("slow.wav"), 0.5)
    assert not worker.alive
