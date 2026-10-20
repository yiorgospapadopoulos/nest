"""B91: Codex chats through the API, on an in-memory `codex app-server`."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.events import types
from nestd.providers.base import AccountInfo, EngineDetails
from nestd.providers.codex_engine import NOT_SIGNED_IN
from tests.api_client import Api, running_api
from tests.codex_support import SIGNED_OUT, item, note, turn_completed
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


@pytest.mark.parametrize("path", ["/api/providers", "/api/models?provider=codex"])
async def test_codex_routes_require_a_device_token(api: Api, path: str) -> None:
    response = await api.http.get(path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_providers_list_the_default_engine_then_codex_with_its_login(api: Api) -> None:
    await api.ctx.engine.report(EngineDetails(models=[], account=AccountInfo(plan="Claude Max")))

    response = await api.http.get("/api/providers")

    assert response.status_code == 200
    default, codex = response.json()["providers"]
    assert (default["name"], default["signed_in"], default["unsupported"]) == ("fake", None, [])
    assert default["account"]["plan"] == "Claude Max"
    assert codex["name"] == "codex"
    assert codex["display_name"] == "Codex"
    assert codex["signed_in"] is True
    assert codex["sign_in_hint"] is None
    assert codex["account"] == {
        "display_name": None,
        "email": "me@example.com",
        "plan": "ChatGPT Plus",
        "organization": None,
    }
    assert {"rewind", "fork", "slash_commands", "plan_review", "memory"} <= set(
        codex["unsupported"]
    )


async def test_a_signed_out_codex_stays_offered_with_how_to_sign_in(
    api: Api, clock: FakeClock
) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT

    cached = (await api.http.get("/api/providers")).json()["providers"][1]
    clock.advance(timedelta(seconds=1))
    refreshed = (await api.http.get("/api/providers?refresh=true")).json()["providers"][1]

    assert cached["signed_in"] is False
    assert refreshed["sign_in_hint"] == NOT_SIGNED_IN
    assert len(api.codex.requests("account/read")) == 2


async def test_codexs_models_and_account_are_served_apart_from_claudes(api: Api) -> None:
    codex = (await api.http.get("/api/models", params={"provider": "codex"})).json()
    claude = (await api.http.get("/api/models")).json()
    account = (await api.http.get("/api/account", params={"provider": "codex"})).json()
    bogus = await api.http.get("/api/models", params={"provider": "gemini"})

    # Only real models, each engine's default named (B94).
    assert [m["value"] for m in codex["models"]] == ["gpt-6.1-sol", "gpt-5.5"]
    assert codex["default_model"] == "gpt-6.1-sol"
    assert codex["models"][0]["effort_levels"] == ["low", "high"]
    assert [m["value"] for m in claude["models"]] == ["opus", "sonnet", "haiku"]
    assert account["plan"] == "ChatGPT Plus"
    assert bogus.status_code == 422


async def test_a_codex_chat_runs_a_turn_on_codex(api: Api) -> None:
    api.codex.script(
        note("turn/started", threadId="thread-1", turn={"id": "turn-1"}),
        note("item/agentMessage/delta", threadId="thread-1", delta="Hi"),
        item("completed", {"type": "agentMessage", "id": "a1", "text": "Hi there"}),
        turn_completed(),
    )

    session = await create(api, provider="codex", mode="in_place")
    session_id = str(session["id"])
    await reach(api, session_id, "idle", results=1)

    # Codex's default model by name, its nearest level to Medium (B94).
    assert (session["provider"], session["model"], session["effort"]) == (
        "codex",
        "gpt-6.1-sol",
        "low",
    )
    detail = (await api.http.get(f"/api/sessions/{session_id}")).json()
    assert detail["provider_session_id"] == "thread-1"
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    messages = [e["payload"]["blocks"] for e in events if e["type"] == types.SESSION_MESSAGE]
    assert messages == [[{"type": "text", "text": "Hi there"}]]
    [turn] = api.codex.requests("turn/start")
    assert turn["input"][-1]["text"].endswith("Do it")  # type: ignore[index]
    assert (turn["model"], turn["effort"]) == ("gpt-6.1-sol", "low")
    assert api.provider.runs == []


async def test_a_codex_chat_while_signed_out_is_refused_with_its_code(api: Api) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT

    response = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "Do it", "provider": "codex"}
    )

    assert response.status_code == 409
    assert response.json() == {"detail": NOT_SIGNED_IN, "code": "codex_not_signed_in"}
    assert (await api.http.get("/api/sessions")).json() == []


async def test_an_unknown_provider_is_a_validation_error(api: Api) -> None:
    response = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "Do it", "provider": "gemini"}
    )

    assert response.status_code == 422
    assert "unknown provider" in response.json()["detail"]


async def test_rewinding_a_codex_chat_is_refused_as_unsupported(api: Api) -> None:
    api.codex.script(turn_completed())
    session_id = str((await create(api, provider="codex", mode="in_place"))["id"])
    await reach(api, session_id, "idle", results=1)

    response = await api.http.get(f"/api/sessions/{session_id}/rewind", params={"message": 1})

    assert response.status_code == 409
    assert response.json()["code"] == "unsupported_feature"
    assert response.json()["feature"] == "rewind"


async def test_removing_a_codex_worktree_chat_drops_its_trust_entry(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    async with running_api(tmp_path, clock, secrets, codex_home=codex_home) as api:
        await api.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        api.codex.script(turn_completed())
        session_id = str((await create(api, provider="codex"))["id"])
        await reach(api, session_id, "idle", results=1)
        worktree = (await api.http.get(f"/api/sessions/{session_id}")).json()["worktree_path"]
        config.write_text(
            f'model = "gpt-5.5"\n\n[projects."{worktree}"]\ntrust_level = "trusted"\n',
            encoding="utf-8",
        )

        closed = await api.http.delete(
            f"/api/sessions/{session_id}", params={"remove_worktree": True}
        )

        assert closed.status_code == 200, closed.text
        assert config.read_text(encoding="utf-8") == 'model = "gpt-5.5"\n\n'
        assert api.codex.launches[0].env["CODEX_HOME"] == str(codex_home)


async def test_a_codex_chat_offers_no_slash_commands(api: Api) -> None:
    api.codex.script(turn_completed())
    session_id = str((await create(api, provider="codex", mode="in_place"))["id"])
    await reach(api, session_id, "idle", results=1)

    response = await api.http.get(f"/api/sessions/{session_id}/commands")

    assert response.json() == {"source": "none", "commands": [], "agents": [], "updated_at": None}
