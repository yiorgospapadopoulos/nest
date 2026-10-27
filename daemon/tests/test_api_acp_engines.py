"""B107: the ACP engines through the API: listed with their install and sign in, offered
for new chats only when ready and signed in, Gemini's key kept in the Keychain only, and
pixies refused on an engine whose git commands Nest cannot block.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from nestd.engine import acp as acp_module
from nestd.engine.acp import key_item
from nestd.events import types
from nestd.providers.acp import AcpProbe
from nestd.providers.acp_engines import GEMINI, OPENCODE
from nestd.providers.acp_process import AcpLaunch, AcpTransportFactory
from tests.acp_engine_support import FREE_MODELS, preinstall
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fakes import FakeClock, FakeSecretStore
from tests.habit_support import published

KEY = "AIza-test-key-0123456789"


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


def by_name(providers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(p["name"]): p for p in providers}


async def test_the_engines_are_listed_in_order_with_their_install_and_sign_in(api: Api) -> None:
    response = await api.http.get("/api/providers")

    assert response.status_code == 200
    providers = response.json()["providers"]
    assert [p["name"] for p in providers] == [
        "fake",
        "codex",
        "opencode",
        "gemini",
        "cursor",
    ]
    listed = by_name(providers)
    assert listed["fake"]["state"] == "ready"
    assert listed["fake"]["sign_in"] == "browser"
    opencode = listed["opencode"]
    assert {key: opencode[key] for key in ("state", "tested", "git_guard", "sign_in")} == {
        "state": "not_installed",
        "tested": True,
        "git_guard": True,
        "sign_in": "terminal",
    }
    assert "rewind" in opencode["unsupported"]
    cursor = listed["cursor"]
    assert (cursor["tested"], cursor["git_guard"], cursor["sign_in"]) == (
        False,
        False,
        "terminal",
    )
    assert "pixies" in cursor["unsupported"]
    assert listed["gemini"]["signed_in"] is False


async def test_installing_from_settings_announces_each_state(api: Api) -> None:
    started = await api.http.post("/api/engines/opencode/install")
    cursor = await api.http.post("/api/engines/cursor/install")
    unknown = await api.http.post("/api/engines/amp/install")

    async def installed() -> bool:
        listed = by_name((await api.http.get("/api/providers")).json()["providers"])
        return listed["opencode"]["state"] == "ready"

    await until(installed)
    assert started.status_code == 202
    assert cursor.status_code == 409
    assert unknown.status_code == 404
    assert api.npm.installs() == ["opencode-ai@1.19.4"]


async def test_an_engine_not_ready_is_not_offered_for_a_new_chat(api: Api, tmp_path: Path) -> None:
    repo = await _repo(api, tmp_path)

    missing = await api.http.post(
        "/api/sessions", json={"repo": repo, "prompt": "hi", "provider": "opencode"}
    )
    preinstall(api.ctx.paths.engines_dir, GEMINI)
    no_key = await api.http.post(
        "/api/sessions", json={"repo": repo, "prompt": "hi", "provider": "gemini"}
    )
    unknown = await api.http.post(
        "/api/sessions", json={"repo": repo, "prompt": "hi", "provider": "amp"}
    )

    assert missing.status_code == 409
    assert missing.json()["code"] == "engine_not_ready"
    assert no_key.status_code == 409
    assert "API key" in no_key.json()["detail"]
    assert unknown.status_code == 422


async def test_a_ready_signed_in_engine_takes_a_new_chat_on_its_default_model(
    api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def probe(launch: AcpLaunch, cwd: Path, transport: AcpTransportFactory) -> AcpProbe:
        del launch, cwd, transport
        return AcpProbe(models=FREE_MODELS, signed_in=True, agent_version=None, mcp_http=True)

    monkeypatch.setattr(acp_module, "probe", probe)
    repo = await _repo(api, tmp_path)
    preinstall(api.ctx.paths.engines_dir, OPENCODE)
    login = tmp_path / "home" / ".local" / "share" / "opencode" / "auth.json"
    login.parent.mkdir(parents=True)
    login.write_text('{"opencode": {"type": "api"}}', encoding="utf-8")
    listed = by_name((await api.http.get("/api/providers")).json()["providers"])

    created = await api.http.post(
        "/api/sessions", json={"repo": repo, "prompt": "hi", "provider": "opencode"}
    )

    assert (listed["opencode"]["state"], listed["opencode"]["signed_in"]) == ("ready", True)
    assert listed["opencode"]["version"] == "1.19.4"
    assert created.status_code == 201, created.text
    assert (created.json()["provider"], created.json()["model"]) == (
        "opencode",
        "opencode/big-pickle",
    )


async def test_geminis_key_is_kept_in_the_keychain_and_never_answered(
    api: Api, secrets: FakeSecretStore
) -> None:
    preinstall(api.ctx.paths.engines_dir, GEMINI)
    listed = (await api.http.get("/api/accounts")).json()["accounts"]
    assert {"opencode-main", "gemini-main", "cursor-main"} <= {a["id"] for a in listed}

    saved = await api.http.put("/api/accounts/gemini-main/key", json={"key": f" {KEY} "})
    providers = by_name((await api.http.get("/api/providers")).json()["providers"])
    removed = await api.http.delete("/api/accounts/gemini-main/key")
    bad = await api.http.put("/api/accounts/gemini-main/key", json={"key": "has spaces in it"})
    wrong = await api.http.put("/api/accounts/opencode-main/key", json={"key": KEY})
    rows = await api.ctx.db.fetch_all("SELECT payload FROM events")

    assert saved.status_code == 200, saved.text
    assert saved.json()["signed_in"] is True
    assert KEY not in saved.text
    assert providers["gemini"]["signed_in"] is True
    assert removed.json()["signed_in"] is False
    assert key_item("gemini-main") not in secrets.values
    assert bad.status_code == 422
    assert "has spaces" not in bad.text
    assert wrong.status_code == 409
    changed = await published(api.ctx, types.ACCOUNTS_CHANGED)
    assert any(by_id(event, "gemini-main")["signed_in"] is True for event in changed)
    assert all(KEY not in row["payload"] for row in rows)


async def test_pixies_refuse_an_engine_without_a_git_guard(api: Api) -> None:
    created = await api.http.post("/api/pixies", json={"name": "C", "provider": "cursor"})
    plain = (await api.http.post("/api/pixies", json={"name": "P"})).json()
    moved = await api.http.patch(f"/api/pixies/{plain['id']}", json={"provider": "cursor"})
    guarded = await api.http.post("/api/pixies", json={"name": "O", "provider": OPENCODE.id})

    assert created.status_code == 409
    assert created.json()["code"] == "unsupported_feature"
    assert created.json()["feature"] == "pixies"
    assert moved.status_code == 409
    assert guarded.status_code == 201, guarded.text


def by_id(event: dict[str, Any], account_id: str) -> dict[str, Any]:
    return next(a for a in event["accounts"] if a["id"] == account_id)


async def _repo(api: Api, tmp_path: Path) -> str:
    folder = tmp_path / "plain"
    folder.mkdir()
    response = await api.http.post("/api/repos", json={"path": str(folder)})
    assert response.status_code in (200, 201), response.text
    return response.json()["name"]
