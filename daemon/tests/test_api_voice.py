"""Voice input through the API (B154): a device token, the model choice saved to the file,
and recordings in, text out."""

import tomllib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.paths import AppPaths
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fakes import FakeClock, FakeSecretStore
from tests.voice_support import FakeWorkers, fake_voice, recording


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


@pytest.fixture
async def workers(api: Api, tmp_path: Path) -> FakeWorkers:
    service, _, fakes = fake_voice(tmp_path / "voice")
    # The real service would fetch with pip; this one makes the files itself.
    await api.ctx.voice.close()
    api.ctx.voice = service
    await api.http.post("/api/voice/install")
    await until(lambda: service.status().state == "ready")
    return fakes


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/voice"),
        ("POST", "/api/voice/install"),
        ("DELETE", "/api/voice"),
        ("PUT", "/api/voice/settings"),
        ("POST", "/api/voice/transcribe"),
    ],
)
async def test_it_requires_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_a_recording_becomes_text(api: Api, workers: FakeWorkers) -> None:
    workers.answers = ["merge it when the checks pass"]

    response = await api.http.post(
        "/api/voice/transcribe", content=recording(), headers={"Content-Type": "audio/wav"}
    )

    assert response.status_code == 200
    assert response.json() == {"text": "merge it when the checks pass"}


async def test_anything_but_a_short_wav_is_refused(api: Api, workers: FakeWorkers) -> None:
    for body in (b"RIFF nonsense", recording(rate=48_000), recording(301)):
        response = await api.http.post("/api/voice/transcribe", content=body)
        assert response.status_code == 422
    assert workers.started == []


async def test_before_the_download_a_recording_is_a_conflict(api: Api) -> None:
    response = await api.http.post("/api/voice/transcribe", content=recording())

    assert response.status_code == 409


async def test_the_model_choice_is_saved(api: Api, tmp_path: Path) -> None:
    status = (await api.http.put("/api/voice/settings", json={"model": "tiny.en"})).json()

    assert status["model"] == "tiny.en"
    assert status["default_model"] == "small.en"
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    written = tomllib.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert written["voice"] == {"model": "tiny.en"}
    assert (await api.http.put("/api/voice/settings", json={"model": "huge"})).status_code == 422
