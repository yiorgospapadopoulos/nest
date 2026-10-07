import tomllib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.providers.base import AccountInfo, EngineDetails, ModelOption
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_engine import LEVELS, server_info
from tests.fake_provider import engine, reply
from tests.fakes import START, FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, reach


async def create_with_defaults(api: Api) -> dict[str, object]:
    response = await api.http.post("/api/sessions", json={"repo": "repo", "prompt": "Do it"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def known_models(api: Api, *values: str) -> None:
    api.engine.info = server_info(*values)
    assert await api.ctx.engine.refresh()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/models"),
        ("GET", "/api/account"),
        ("GET", "/api/agents/defaults"),
        ("PUT", "/api/agents/defaults"),
    ],
)
async def test_engine_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_before_the_engine_reported_the_aliases_and_an_empty_account_show(
    api: Api,
) -> None:
    models = (await api.http.get("/api/models")).json()
    account = (await api.http.get("/api/account")).json()

    assert [m["value"] for m in models["models"]] == ["default", "opus", "sonnet", "haiku"]
    assert models["updated_at"] is None
    assert models["models"][3] == {
        "value": "haiku",
        "display_name": "Haiku",
        "description": "Fastest, for quick answers",
        "effort_levels": [],
        "supports_effort": False,
    }
    assert account == {"display_name": None, "email": None, "plan": None, "organization": None}


async def test_the_engine_list_and_account_are_served_in_claude_codes_order(api: Api) -> None:
    await known_models(api, "default", "opus", "haiku", "claude-opus-4-8")

    models = (await api.http.get("/api/models")).json()
    account = (await api.http.get("/api/account")).json()

    assert models["updated_at"] == START.isoformat().replace("+00:00", "Z")
    assert [m["value"] for m in models["models"]] == [
        "default",
        "opus",
        "haiku",
        "claude-opus-4-8",
    ]
    assert models["models"][1] == {
        "value": "opus",
        "display_name": "Opus",
        "description": "opus model",
        "effort_levels": LEVELS,
        "supports_effort": True,
    }
    assert account == {
        "display_name": None,
        "email": "person@example.com",
        "plan": "Claude Max",
        "organization": "Acme",
    }


async def test_a_session_run_refreshes_the_list(api: Api) -> None:
    reported = EngineDetails(
        models=[ModelOption(value="sonnet", display_name="Sonnet 5.5", description="Everyday")],
        account=AccountInfo(plan="Claude Pro"),
    )
    api.provider.script(engine(reported, reply("ok")))

    session = await create(api)
    await reach(api, str(session["id"]), "idle")

    async def listed() -> bool:
        models = (await api.http.get("/api/models")).json()["models"]
        return [m["value"] for m in models] == ["sonnet"]

    await until(listed)
    assert (await api.http.get("/api/account")).json()["plan"] == "Claude Pro"


async def test_agent_defaults_start_in_place_with_claude_codes_choices(api: Api) -> None:
    defaults = (await api.http.get("/api/agents/defaults")).json()

    assert defaults == {
        "model": None,
        "effort": None,
        "permission_mode": "default",
        "mode": "in_place",
    }


async def test_agent_defaults_are_saved_and_used_for_new_sessions(api: Api) -> None:
    api.ctx.paths.settings_file.write_text(
        "[agents]\nidle_close_minutes = 20\n[usage]\nrefresh_minutes = 5\n", encoding="utf-8"
    )
    chosen = {"model": "opus", "effort": "high", "permission_mode": "plan", "mode": "worktree"}

    saved = await api.http.put("/api/agents/defaults", json=chosen)
    api.provider.script(reply("ok"))
    session = await create_with_defaults(api)

    assert saved.status_code == 200
    assert saved.json() == chosen
    assert (await api.http.get("/api/agents/defaults")).json() == chosen
    data = tomllib.loads(api.ctx.paths.settings_file.read_text(encoding="utf-8"))
    assert data["agents"] == {
        "model": "opus",
        "effort": "high",
        "permission_mode": "plan",
        "default_mode": "worktree",
        "idle_close_minutes": 20,
    }
    assert data["usage"] == {"refresh_minutes": 5}
    assert (session["model"], session["effort"], session["permission_mode"]) == (
        "opus",
        "high",
        "plan",
    )
    assert session["mode"] == "worktree"


async def test_new_sessions_work_in_place_by_default(api: Api) -> None:
    api.provider.script(reply("ok"))

    session = await create_with_defaults(api)

    assert session["mode"] == "in_place"


async def test_effort_is_checked_against_the_engine_list(api: Api) -> None:
    await known_models(api, "default", "opus", "haiku")

    refused = await api.http.put(
        "/api/agents/defaults", json={"model": "haiku", "effort": "low", "mode": "in_place"}
    )
    haiku = await api.http.put("/api/agents/defaults", json={"model": "haiku", "effort": None})
    session = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "x", "model": "haiku", "effort": "max"}
    )

    assert refused.status_code == 422
    assert refused.json() == {"detail": "Haiku does not take a thinking level"}
    assert haiku.status_code == 200
    assert haiku.json() == {
        "model": "haiku",
        "effort": None,
        "permission_mode": "default",
        "mode": "in_place",
    }
    assert session.status_code == 422
    assert session.json() == {"detail": "Haiku does not take a thinking level"}


async def test_unlisted_models_and_the_fallback_list_are_not_checked(api: Api) -> None:
    fallback = await api.http.put("/api/agents/defaults", json={"model": "haiku", "effort": "low"})
    await known_models(api, "opus")
    unlisted = await api.http.put(
        "/api/agents/defaults", json={"model": "claude-opus-4-1", "effort": "max"}
    )

    assert fallback.status_code == 200
    assert unlisted.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"model": ""},
        {"effort": "huge"},
        {"permission_mode": "auto"},
        {"mode": "elsewhere"},
        {"idle_close_minutes": 5},
    ],
)
async def test_invalid_agent_defaults_are_refused(api: Api, body: dict[str, object]) -> None:
    response = await api.http.put("/api/agents/defaults", json=body)

    assert response.status_code == 422


async def test_agent_defaults_never_overwrite_a_broken_settings_file(api: Api) -> None:
    api.ctx.paths.settings_file.write_text("[agents\n", encoding="utf-8")

    response = await api.http.put("/api/agents/defaults", json={})

    assert response.status_code == 409
    assert api.ctx.paths.settings_file.read_text(encoding="utf-8") == "[agents\n"
