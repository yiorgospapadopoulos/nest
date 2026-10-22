"""B106: local models through the API, on mocked model servers."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.local.models import local_ref
from nestd.local.store import model_id, server_id
from nestd.local.translate.upstream import Upstream
from nestd.providers.base import TokenUsage
from tests.api_client import Api, running_api
from tests.codex_support import SIGNED_OUT, turn_completed
from tests.fake_engine import server_info
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.local_support import LocalMac, llama_cpp, lm_studio
from tests.test_api_sessions import create, reach

LMS = server_id("127.0.0.1:1234")
CODER = model_id(LMS, "qwen/qwen3-coder-30b")


@pytest.fixture
def mac(tmp_path: Path) -> LocalMac:
    return LocalMac(tmp_path / "mac")


@pytest.fixture
async def api(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, mac: LocalMac
) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets, local_setup=mac.setup()) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def add_coder(api: Api, mac: LocalMac) -> None:
    mac.network.add(lm_studio())
    response = await api.http.post(
        "/api/local/models",
        json={"address": "127.0.0.1:1234", "key": None, "models": ["qwen/qwen3-coder-30b"]},
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/local/models"),
        ("GET", "/api/local/find"),
        ("POST", "/api/local/check"),
        ("DELETE", "/api/local/models/x"),
        ("PUT", "/api/local/engine"),
        ("POST", "/api/local/start"),
        ("GET", "/api/local/usage"),
        ("GET", "/api/setup"),
        ("POST", "/api/setup/local-only"),
    ],
)
async def test_the_routes_need_a_device(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": ""})

    assert response.status_code == 401


async def test_models_are_checked_added_listed_and_removed(api: Api, mac: LocalMac) -> None:
    assert (await api.http.get("/api/local/models")).json() == {
        "models": [],
        "engine": "claude",
        "local_only": False,
    }
    mac.network.add(lm_studio())

    checked = await api.http.post(
        "/api/local/check", json={"address": "http://127.0.0.1:1234", "key": "sk"}
    )
    assert checked.status_code == 200
    assert checked.json()["ok"]
    assert checked.json()["server"]["app"] == "LM Studio"
    added = await api.http.post(
        "/api/local/models",
        json={"address": "127.0.0.1:1234", "key": "sk", "models": ["qwen/qwen3-coder-30b"]},
    )

    assert added.status_code == 201
    [model] = added.json()["models"]
    assert (model["id"], model["running"], model["has_key"]) == (CODER, True, True)
    listed = (await api.http.get("/api/local/models")).json()["models"]
    assert [entry["id"] for entry in listed] == [CODER]
    assert await api.ctx.local.resolve(LMS) == Upstream(
        "http://127.0.0.1:1234",
        "sk",
        messages=True,
        usage_counts_cache=True,
        app="LM Studio",
        contexts={"qwen/qwen3-coder-30b": 65536},
    )

    assert (await api.http.delete(f"/api/local/models/{CODER}")).status_code == 204
    assert (await api.http.delete(f"/api/local/models/{CODER}")).status_code == 404
    assert (await api.http.get("/api/local/models")).json()["models"] == []


async def test_bad_requests_are_refused(api: Api, mac: LocalMac) -> None:
    bad_address = await api.http.post("/api/local/check", json={"address": "host:port"})
    assert bad_address.status_code == 422
    no_models = await api.http.post(
        "/api/local/models", json={"address": "127.0.0.1:1234", "models": []}
    )
    assert no_models.status_code == 422
    down = await api.http.post(
        "/api/local/models", json={"address": "127.0.0.1:1234", "models": ["m"]}
    )
    assert down.status_code == 409
    assert down.json()["code"] == "local_server_down"
    mac.network.add(lm_studio())
    unknown = await api.http.post(
        "/api/local/models", json={"address": "127.0.0.1:1234", "models": ["nope"]}
    )
    assert unknown.status_code == 422


async def test_find_lists_what_runs_and_what_is_downloaded(api: Api, mac: LocalMac) -> None:
    # Ollama is not running, so its download shows with a way to start it.
    mac.network.add(llama_cpp())
    manifest = mac.folders.ollama_models / "manifests" / "registry.ollama.ai" / "library"
    (manifest / "gemma3").mkdir(parents=True)
    (manifest / "gemma3" / "4b").write_text("{}")
    mac.installed["ollama"] = "/opt/homebrew/bin/ollama"

    found = (await api.http.get("/api/local/find")).json()

    assert [model["model"] for model in found["running"]] == ["Qwen3-14B-Q4_K_M.gguf"]
    assert found["downloaded"] == [
        {
            "name": "gemma3:4b",
            "source": "Ollama",
            "path": str(manifest / "gemma3" / "4b"),
            "hint": "Downloaded with Ollama: start Ollama to use it.",
            "start": "ollama",
        }
    ]


async def test_the_engine_and_starting_an_app(api: Api, mac: LocalMac) -> None:
    assert (await api.http.put("/api/local/engine", json={"engine": "codex"})).status_code == 204
    assert (await api.http.get("/api/local/models")).json()["engine"] == "codex"
    assert (await api.http.put("/api/local/engine", json={"engine": "x"})).status_code == 422

    assert (await api.http.post("/api/local/start", json={"app": "ollama"})).status_code == 404
    mac.installed["ollama"] = "/opt/homebrew/bin/ollama"
    assert (await api.http.post("/api/local/start", json={"app": "ollama"})).status_code == 202
    assert mac.launched == [["/opt/homebrew/bin/ollama", "serve"]]


async def test_usage_counts_todays_local_tokens(api: Api) -> None:
    await api.ctx.local.record_usage(CODER, TokenUsage(input_tokens=100, output_tokens=20))

    assert (await api.http.get("/api/local/usage")).json() == {
        "today_tokens": 120,
        "models": [{"id": CODER, "input_tokens": 100, "output_tokens": 20}],
    }


async def test_the_first_run_until_the_user_chooses(api: Api) -> None:
    assert (await api.http.get("/api/setup")).json() == {"first_run": True, "local_only": False}

    chosen = await api.http.post("/api/setup/local-only")

    assert chosen.json() == {"first_run": False, "local_only": True}
    assert (await api.http.get("/api/local/models")).json()["local_only"]


async def test_the_first_run_ends_when_the_user_says(api: Api) -> None:
    done = await api.http.post("/api/setup/done")

    assert done.json() == {"first_run": False, "local_only": False}


async def test_a_local_chat_on_codex_runs_without_a_codex_login(api: Api, mac: LocalMac) -> None:
    await add_coder(api, mac)
    await api.http.put("/api/local/engine", json={"engine": "codex"})
    api.codex.answers["account/read"] = SIGNED_OUT
    api.codex.script(turn_completed())

    session = await create(api, model=local_ref(CODER), mode="in_place")
    await reach(api, str(session["id"]), "idle", results=1)

    assert (session["provider"], session["model"]) == ("codex", local_ref(CODER))
    [start] = api.codex.requests("thread/start")
    assert start["model"] == "qwen/qwen3-coder-30b"
    assert start["config"]["model_provider"] == "nestlocal"  # type: ignore[index]
    assert start["config"]["model_providers.nestlocal.base_url"] == (  # type: ignore[index]
        "http://127.0.0.1:1234/v1"
    )


async def test_a_chat_on_a_stopped_server_is_refused_with_how_to_start_it(
    api: Api, mac: LocalMac, clock: FakeClock
) -> None:
    await add_coder(api, mac)
    mac.network.servers["127.0.0.1:1234"].down = True
    clock.advance(timedelta(seconds=5))

    response = await api.http.post(
        "/api/sessions",
        json={"repo": "repo", "prompt": "Do it", "mode": "in_place", "model": local_ref(CODER)},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "LM Studio at 127.0.0.1:1234 is not running",
        "code": "local_server_down",
        "app": "LM Studio",
        "address": "127.0.0.1:1234",
        "start": None,
    }


async def test_with_nothing_signed_in_the_defaults_are_the_first_local_model(
    api: Api, mac: LocalMac
) -> None:
    await add_coder(api, mac)
    await api.http.put("/api/local/engine", json={"engine": "codex"})

    defaults = (await api.http.get("/api/agents/defaults")).json()

    assert (defaults["provider"], defaults["model"]) == ("codex", local_ref(CODER))
    # Not stored: a sign in later brings the engine's own default back.
    assert api.ctx.settings.agents.model is None


async def test_defaults_read_before_any_local_model_are_not_kept_while_nothing_is_signed_in(
    api: Api, mac: LocalMac
) -> None:
    # Live (fresh setup): the Mac app read the defaults on its first open, Claude's
    # fallback Opus was stored, and the phone's new chats then ran on Opus with no login.
    # Claude Code lists its models but no account: nothing is signed in.
    info = server_info("default", "opus", "haiku")
    info["account"] = {}
    api.engine.info = info
    await api.ctx.engine.refresh()
    first = (await api.http.get("/api/agents/defaults")).json()
    assert first["model"] == "opus"
    assert api.ctx.settings.agents.model is None

    await add_coder(api, mac)
    later = (await api.http.get("/api/agents/defaults")).json()

    assert later["model"] == local_ref(CODER)


async def test_a_new_chat_is_taken_at_once_and_the_model_loads_in_its_turn(
    api: Api, mac: LocalMac
) -> None:
    """Live: the load held the message in the composer for 11 s inside the request."""
    server = mac.network.add(lm_studio())
    added = await api.http.post(
        "/api/local/models", json={"address": "127.0.0.1:1234", "models": ["qwen/qwen3-4b"]}
    )
    small = added.json()["models"][0]["id"]
    api.provider.script(reply("done"))

    session = await create(api, model=local_ref(small), mode="in_place")
    session_id = str(session["id"])
    await reach(api, session_id, "idle", results=1)

    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    kinds = [e["type"] for e in events]
    assert kinds.index("session.user_message") < kinds.index("session.notice")
    notices = [e["payload"] for e in events if e["type"] == "session.notice"]
    assert notices == [{"kind": "loading_model", "text": "Loading qwen3-4b in LM Studio"}]
    assert [r.url.path for r in server.requests].count("/api/v1/models/load") == 1
    assert api.provider.runs[0].spec.local is not None
    assert api.provider.runs[0].spec.local.context == 40960


async def test_the_translator_is_served_and_wants_the_daemons_key(api: Api, mac: LocalMac) -> None:
    await add_coder(api, mac)

    response = await api.http.post(
        f"/local/{LMS}/v1/messages", json={}, headers={"Authorization": "Bearer wrong"}
    )

    assert response.status_code in (401, 403)
