"""B94: new chats and pixies start from real models, levels and modes, never "default".

Nothing chosen means: the default model of the engine the user signed in to first, the
thinking level Medium (or the closest one the model takes) and Ask. Stored settings
that deferred to the engine become these concrete values.
"""

import tomllib
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.providers.base import AccountInfo, EngineDetails
from tests.api_client import Api, running_api
from tests.fake_engine import server_info
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def claude_models(api: Api, *values: str, auto: tuple[str, ...] = ()) -> None:
    api.engine.info = server_info(*values, auto=auto)
    assert await api.ctx.engine.refresh()


async def codex_models(api: Api) -> None:
    """Codex reports its list (default GPT-6.1 Sol with low and high, GPT-5.5 without)."""
    await api.ctx.codex.status(refresh=True)


def stored_agents(api: Api) -> dict[str, object]:
    return tomllib.loads(api.ctx.paths.settings_file.read_text(encoding="utf-8"))["agents"]


async def start_chat(api: Api, **choices: object) -> dict[str, object]:
    api.provider.script(reply("ok"))
    body = {"repo": "repo", "prompt": "Do it"} | choices
    response = await api.http.post("/api/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_without_choices_the_first_engines_default_model_medium_and_ask_are_stored(
    api: Api,
) -> None:
    await claude_models(api, "default", "opus", "haiku")
    # Codex is signed in too, but Claude was first.
    await api.ctx.sign_ins.record("claude")
    await codex_models(api)

    defaults = (await api.http.get("/api/agents/defaults")).json()

    assert defaults == {
        "provider": "fake",
        "model": "opus",
        "effort": "medium",
        "permission_mode": "default",
        "mode": "in_place",
    }
    assert stored_agents(api) == {
        "provider": "fake",
        "model": "opus",
        "effort": "medium",
        "permission_mode": "default",
        "default_mode": "in_place",
        "idle_close_minutes": 60,
    }


async def test_codex_first_makes_its_default_model_the_default(api: Api, clock: FakeClock) -> None:
    await codex_models(api)
    clock.advance(timedelta(minutes=1))
    await claude_models(api, "default", "opus")

    defaults = (await api.http.get("/api/agents/defaults")).json()

    # Codex was the only engine seen signed in; its model takes low or high, not medium.
    assert (defaults["provider"], defaults["model"], defaults["effort"]) == (
        "codex",
        "gpt-6.1-sol",
        "low",
    )


async def test_before_any_model_list_is_known_nothing_is_stored(api: Api) -> None:
    defaults = (await api.http.get("/api/agents/defaults")).json()

    assert defaults == {
        "provider": "fake",
        "model": None,
        "effort": None,
        "permission_mode": "default",
        "mode": "in_place",
    }
    assert "model" not in stored_agents(api)


async def test_older_defaults_that_left_choices_to_claude_code_become_concrete(
    api: Api,
) -> None:
    api.ctx.paths.settings_file.write_text(
        '[agents]\nmodel = "haiku"\nidle_close_minutes = 20\n', encoding="utf-8"
    )
    api.ctx.settings = api.ctx.settings.model_copy(
        update={"agents": api.ctx.settings.agents.model_copy(update={"model": "haiku"})}
    )
    await claude_models(api, "default", "opus", "haiku")

    defaults = (await api.http.get("/api/agents/defaults")).json()

    # Haiku takes no thinking level, so none is set; the mode is Ask.
    assert defaults == {
        "provider": "fake",
        "model": "haiku",
        "effort": None,
        "permission_mode": "default",
        "mode": "in_place",
    }
    assert stored_agents(api) == {
        "provider": "fake",
        "model": "haiku",
        "permission_mode": "default",
        "default_mode": "in_place",
        "idle_close_minutes": 20,
    }


async def test_settling_at_startup_converts_stored_defaults(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    async with running_api(tmp_path, clock, secrets) as first:
        await claude_models(first, "default", "sonnet")
    (tmp_path / "config" / "settings.toml").write_text("[agents]\n", encoding="utf-8")

    async with running_api(tmp_path, clock, secrets) as restarted:
        assert stored_agents(restarted)["model"] == "sonnet"
        assert restarted.ctx.settings.agents.effort == "medium"


async def test_old_clients_sending_nulls_or_default_get_concrete_values(api: Api) -> None:
    await claude_models(api, "default", "opus", "haiku")

    nulls = await api.http.put(
        "/api/agents/defaults",
        json={"model": None, "effort": None, "permission_mode": None, "mode": "in_place"},
    )
    named_default = await api.http.put("/api/agents/defaults", json={"model": "default"})

    assert nulls.status_code == 200
    assert nulls.json() == {
        "provider": "fake",
        "model": "opus",
        "effort": "medium",
        "permission_mode": "default",
        "mode": "in_place",
    }
    assert named_default.json()["model"] == "opus"
    assert stored_agents(api)["permission_mode"] == "default"


async def test_choosing_a_codex_model_makes_codex_the_engine_of_new_chats(api: Api) -> None:
    await claude_models(api, "default", "opus")
    await codex_models(api)

    saved = await api.http.put(
        "/api/agents/defaults", json={"provider": "codex", "model": "gpt-5.5", "mode": "in_place"}
    )
    session = await start_chat(api)

    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "provider": "codex",
        "model": "gpt-5.5",
        "effort": None,
        "permission_mode": "default",
        "mode": "in_place",
    }
    assert stored_agents(api)["provider"] == "codex"
    assert (session["provider"], session["model"], session["effort"]) == ("codex", "gpt-5.5", None)


async def test_a_codex_default_is_checked_against_codexs_models(api: Api) -> None:
    await codex_models(api)

    effort = await api.http.put(
        "/api/agents/defaults",
        json={"provider": "codex", "model": "gpt-5.5", "effort": "high"},
    )
    unknown = await api.http.put("/api/agents/defaults", json={"provider": "gemini"})

    assert effort.status_code == 422
    assert effort.json() == {"detail": "GPT-5.5 does not take a thinking level"}
    assert unknown.status_code == 422


async def test_a_chat_with_nothing_chosen_passes_every_choice_explicitly(api: Api) -> None:
    api.ctx.paths.settings_file.write_text("[agents]\n", encoding="utf-8")
    await claude_models(api, "default", "opus")

    session = await start_chat(api)
    await reach(api, str(session["id"]), "idle")

    assert (session["model"], session["effort"], session["permission_mode"]) == (
        "opus",
        "medium",
        "default",
    )
    assert session["follows_claude_code_mode"] is False
    spec = api.provider.runs[0].spec
    assert (spec.model, spec.effort, spec.permission_mode) == ("opus", "medium", "default")


async def test_a_codex_chat_without_a_model_starts_on_codexs_concrete_default(api: Api) -> None:
    await claude_models(api, "default", "opus")
    await codex_models(api)
    await api.ctx.sign_ins.record("claude")

    session = await start_chat(api, provider="codex", model="default")

    assert (session["model"], session["effort"], session["permission_mode"]) == (
        "gpt-6.1-sol",
        "low",
        "default",
    )


async def test_new_pixies_get_concrete_models_and_thinking(api: Api) -> None:
    await claude_models(api, "default", "opus", "haiku")
    await codex_models(api)
    await api.ctx.sign_ins.record("claude")

    claude = (await api.http.post("/api/pixies", json={"name": "Ada"})).json()
    codex = (await api.http.post("/api/pixies", json={"name": "Bo", "provider": "codex"})).json()
    reset = await api.http.patch(
        f"/api/pixies/{claude['id']}", json={"model": None, "effort": None}
    )
    moved = await api.http.patch(f"/api/pixies/{claude['id']}", json={"provider": "codex"})

    assert (claude["model"], claude["effort"]) == ("opus", "medium")
    assert (codex["model"], codex["effort"]) == ("gpt-6.1-sol", "low")
    assert (reset.json()["model"], reset.json()["effort"]) == ("opus", "medium")
    assert (moved.json()["model"], moved.json()["effort"]) == ("gpt-6.1-sol", "low")


async def test_stored_pixies_and_pixie_defaults_become_concrete(api: Api) -> None:
    await claude_models(api, "default", "opus", "haiku")
    await api.ctx.sign_ins.record("claude")
    created = (await api.http.post("/api/pixies", json={"name": "Ada"})).json()
    await api.ctx.db.execute(
        "UPDATE pixies SET model = NULL, effort = NULL WHERE id = ?", (created["id"],)
    )
    api.ctx.paths.settings_file.write_text('[agents]\nmodel = "haiku"\n', encoding="utf-8")
    api.ctx.settings = api.ctx.settings.model_copy(
        update={"agents": api.ctx.settings.agents.model_copy(update={"model": "haiku"})}
    )

    await api.http.get("/api/agents/defaults")
    pixie = (await api.http.get(f"/api/pixies/{created['id']}")).json()
    settings = (await api.http.get("/api/pixie-settings")).json()

    # A Claude pixie that followed the agent defaults keeps their model, now its own.
    assert (pixie["model"], pixie["effort"]) == ("haiku", None)
    assert settings["model"] == "haiku"
    data = tomllib.loads(api.ctx.paths.settings_file.read_text(encoding="utf-8"))
    assert data["pixies"]["model"] == "haiku"


async def test_a_pixie_without_a_resolved_model_gets_one_when_it_runs(api: Api) -> None:
    created = (await api.http.post("/api/pixies", json={"name": "Ada"})).json()
    assert created["model"] is None
    await api.ctx.engine.report(EngineDetails(models=None, account=AccountInfo(plan="Claude Pro")))
    await claude_models(api, "default", "sonnet")
    api.provider.script(reply("ok"))

    sent = await api.http.post(f"/api/pixies/{created['id']}/messages", json={"text": "Hi"})
    pixie = (await api.http.get(f"/api/pixies/{created['id']}")).json()

    assert sent.status_code == 202, sent.text
    assert (pixie["model"], pixie["effort"]) == ("sonnet", "medium")
    assert sent.json()["model"] == "sonnet"


async def test_a_settings_file_broken_meanwhile_is_left_alone(api: Api) -> None:
    await claude_models(api, "default", "opus")
    api.ctx.paths.settings_file.write_text("[agents\n", encoding="utf-8")

    defaults = await api.http.get("/api/agents/defaults")

    assert defaults.status_code == 200
    assert defaults.json()["model"] == "opus"
    assert api.ctx.paths.settings_file.read_text(encoding="utf-8") == "[agents\n"


async def codex_defaults(api: Api) -> None:
    await claude_models(api, "default", "opus", "haiku")
    await codex_models(api)
    saved = await api.http.put(
        "/api/agents/defaults", json={"provider": "codex", "model": "gpt-5.5", "mode": "in_place"}
    )
    assert saved.status_code == 200


async def test_an_older_client_naming_a_claude_model_moves_the_defaults_to_claude(
    api: Api,
) -> None:
    await codex_defaults(api)

    # The iPhone before B92 sends no engine.
    claude = await api.http.put(
        "/api/agents/defaults",
        json={"model": "haiku", "effort": None, "permission_mode": None, "mode": "in_place"},
    )

    assert (claude.json()["provider"], claude.json()["model"]) == ("fake", "haiku")


async def test_an_older_client_changing_other_choices_keeps_the_engine(api: Api) -> None:
    await codex_defaults(api)

    same = await api.http.put(
        "/api/agents/defaults", json={"model": "gpt-5.5", "permission_mode": "plan"}
    )
    unnamed = await api.http.put("/api/agents/defaults", json={"mode": "worktree"})

    assert (same.json()["provider"], same.json()["permission_mode"]) == ("codex", "plan")
    assert (unnamed.json()["provider"], unnamed.json()["model"]) == ("codex", "gpt-6.1-sol")


async def test_an_older_clients_chat_runs_on_the_engine_of_the_model_it_names(api: Api) -> None:
    await codex_defaults(api)

    claude = await start_chat(api, model="opus")
    unlisted = await start_chat(api, model="claude-opus-4-1")
    codex = await start_chat(api)

    assert (claude["provider"], claude["model"]) == ("fake", "opus")
    assert (unlisted["provider"], unlisted["model"]) == ("fake", "claude-opus-4-1")
    assert (codex["provider"], codex["model"]) == ("codex", "gpt-5.5")
