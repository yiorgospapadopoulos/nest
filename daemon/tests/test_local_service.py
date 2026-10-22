from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue

from nestd.errors import InvalidInputError
from nestd.events.bus import EventBus
from nestd.events.models import Event
from nestd.local.discovery import ModelFolders
from nestd.local.errors import (
    AppNotInstalledError,
    LocalModelNotFoundError,
    LocalModelNotLoadedError,
    LocalServerDownError,
)
from nestd.local.models import LocalModelUsage, SetupState, local_ref
from nestd.local.run import PLACEHOLDER_KEY
from nestd.local.service import LocalModels, LocalSetup, key_account, launch_detached
from nestd.local.store import LocalStore, model_id, server_id
from nestd.local.translate.upstream import Upstream
from nestd.providers.base import TokenUsage
from nestd.storage.db import Database
from tests.fakes import FakeClock, FakeSecretStore
from tests.local_support import ModelServer, Network, llama_cpp, lm_studio, mlx, ollama

LMS = server_id("127.0.0.1:1234")
CODER = model_id(LMS, "qwen/qwen3-coder-30b")
SMALL = model_id(LMS, "qwen/qwen3-4b")
CHANGED = "local_models.changed"
GB12 = 12 * 1024**3
MEMORY = 24 * 1024**3


class RecordingBus(EventBus):
    def __init__(self, db: Database, clock: FakeClock) -> None:
        super().__init__(db, clock)
        self.ephemeral: list[str] = []

    async def publish_ephemeral(
        self, event_type: str, payload: Mapping[str, JsonValue], session_id: str | None = None
    ) -> Event:
        self.ephemeral.append(event_type)
        return await super().publish_ephemeral(event_type, payload, session_id)


class Env:
    def __init__(self, tmp_path: Path, db: Database, clock: FakeClock) -> None:
        self.network = Network()
        self.secrets = FakeSecretStore()
        self.clock = clock
        self.bus = RecordingBus(db, clock)
        self.launched: list[list[str]] = []
        self.installed: dict[str, str] = {}
        self.signed_in = False
        self.claude_signed_in = False
        self.folders = ModelFolders(
            lmstudio_models=tmp_path / "lms" / "models",
            lms=tmp_path / "lms" / "bin" / "lms",
            ollama_models=tmp_path / "ollama",
            huggingface_hub=tmp_path / "hf",
            llama_cpp=tmp_path / "llama.cpp",
        )
        self.db = db
        self.local = self.build()

    def build(self) -> LocalModels:
        async def launch(command: Sequence[str]) -> None:
            self.launched.append(list(command))

        async def signed_in() -> bool:
            return self.signed_in

        async def claude() -> bool:
            return self.claude_signed_in

        return LocalModels(
            store=LocalStore(self.db),
            secrets=self.secrets,
            bus=self.bus,
            clock=self.clock,
            port=lambda: 8765,
            setup=LocalSetup(
                self.folders, self.network.transport(), self.installed.get, launch, lambda: MEMORY
            ),
            zone=UTC,
            signed_in=signed_in,
            claude_signed_in=claude,
        )

    def install_lms(self) -> None:
        self.folders.lms.parent.mkdir(parents=True)
        self.folders.lms.write_text("#!/bin/sh\n")


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    built = Env(tmp_path, db, clock)
    yield built
    await built.local.close()


async def test_adding_stores_the_server_its_key_and_the_chosen_models(env: Env) -> None:
    env.network.add(lm_studio())

    added = await env.local.add("http://127.0.0.1:1234/v1", "sk", ["qwen/qwen3-coder-30b"])

    assert [model.model_dump() for model in added] == [
        {
            "id": CODER,
            "server_id": LMS,
            "model": "qwen/qwen3-coder-30b",
            "name": "qwen3-coder-30b",
            "address": "127.0.0.1:1234",
            "app": "LM Studio",
            "context": 65536,
            "tools": "good",
            "weak_reason": None,
            "vision": False,
            "thinking": False,
            "running": True,
            "has_key": True,
            "memory_warning": None,
        }
    ]
    assert env.secrets.values == {key_account(LMS): "sk"}
    # LM Studio counts cache reads in its input tokens.
    assert await env.local.resolve(LMS) == Upstream(
        "http://127.0.0.1:1234",
        "sk",
        messages=True,
        usage_counts_cache=True,
        app="LM Studio",
        contexts={"qwen/qwen3-coder-30b": 65536},
    )
    assert env.bus.ephemeral == [CHANGED]


async def test_more_models_of_a_server_keep_its_key_and_order(env: Env) -> None:
    env.network.add(lm_studio())
    await env.local.add("127.0.0.1:1234", "sk", ["qwen/qwen3-coder-30b"])

    await env.local.add("127.0.0.1:1234", None, ["qwen/qwen3-4b", "qwen/qwen3-coder-30b"])

    listed = await env.local.listing()
    assert [(m.id, m.has_key, m.tools) for m in listed.models] == [
        (CODER, True, "good"),
        (SMALL, True, "weak"),
    ]
    assert (listed.engine, listed.local_only) == ("claude", False)
    # The second check used the stored key.
    server = env.network.servers["127.0.0.1:1234"]
    assert server.requests[-1].headers["authorization"] == "Bearer sk"


async def test_a_model_the_server_does_not_serve_is_refused(env: Env) -> None:
    env.network.add(lm_studio())

    with pytest.raises(InvalidInputError, match="does not serve nope"):
        await env.local.add("127.0.0.1:1234", None, ["nope"])

    assert (await env.local.listing()).models == []


async def test_adding_from_a_server_that_does_not_answer_is_refused(env: Env) -> None:
    with pytest.raises(LocalServerDownError) as raised:
        await env.local.add("127.0.0.1:1234", None, ["m"])

    assert raised.value.payload() == {
        "detail": "The model's server at 127.0.0.1:1234 is not running",
        "code": "local_server_down",
        "app": None,
        "address": "127.0.0.1:1234",
        "start": None,
    }


async def test_whether_a_server_runs_is_asked_again_after_a_few_seconds(env: Env) -> None:
    server = env.network.add(lm_studio())
    await env.local.add("127.0.0.1:1234", None, ["qwen/qwen3-coder-30b"])
    server.down = True

    assert [m.running for m in (await env.local.listing()).models] == [True]
    env.clock.advance(timedelta(seconds=3))
    assert [m.running for m in (await env.local.listing()).models] == [False]


async def test_a_server_without_a_key_is_resolved_without_one(env: Env) -> None:
    env.network.add(mlx())
    await env.local.add("127.0.0.1:8080", "", ["mlx-community/Qwen3-32B-4bit"])

    restarted = env.build()
    assert await restarted.resolve(server_id("127.0.0.1:8080")) is None
    await restarted.load()
    assert await restarted.resolve(server_id("127.0.0.1:8080")) == Upstream(
        "http://127.0.0.1:8080", None, messages=False
    )
    assert env.secrets.values == {}
    await restarted.close()


async def test_removing_the_last_model_removes_the_server_and_its_key(env: Env) -> None:
    env.network.add(lm_studio())
    await env.local.add("127.0.0.1:1234", "sk", ["qwen/qwen3-coder-30b", "qwen/qwen3-4b"])

    await env.local.remove(CODER)
    assert await env.local.resolve(LMS) is not None
    await env.local.remove(SMALL)

    assert (await env.local.listing()).models == []
    assert await env.local.resolve(LMS) is None
    assert env.secrets.values == {}
    assert env.bus.ephemeral == [CHANGED, CHANGED, CHANGED]
    with pytest.raises(LocalModelNotFoundError):
        await env.local.remove(SMALL)


async def test_check_describes_the_server_and_its_models(env: Env) -> None:
    env.network.add(ollama())
    await env.local.add("127.0.0.1:11434", None, ["gemma3:27b"])

    result = await env.local.check("127.0.0.1:11434", None)

    assert result.ok
    assert result.error is None
    assert result.server is not None
    assert result.server.model_dump() == {
        "address": "127.0.0.1:11434",
        "app": "Ollama",
        "messages": True,
        "responses": True,
        "chat": True,
    }
    assert [(m.model, m.tools, m.added) for m in result.models] == [
        ("qwen3:32b", "weak", False),
        ("gemma3:27b", "none", True),
    ]


async def test_check_says_why_a_server_cannot_be_used(env: Env) -> None:
    unreachable = await env.local.check("127.0.0.1:1234", "k")
    assert (unreachable.ok, unreachable.error, unreachable.server) == (False, "unreachable", None)

    empty = env.network.add(mlx(port=8001))
    empty.models()
    assert (await env.local.check("127.0.0.1:8001", None)).error == "no_models"

    toolless = env.network.add(ollama(port=11435))
    toolless.models({"id": "gemma3:27b"})
    assert (await env.local.check("127.0.0.1:11435", None)).error == "no_tools"


async def test_find_lists_running_and_downloaded_models(env: Env) -> None:
    env.network.add(lm_studio())
    env.network.add(llama_cpp())
    await env.local.add("127.0.0.1:1234", None, ["qwen/qwen3-4b"])
    repo = env.folders.lmstudio_models / "qwen" / "Qwen3-Coder-30B-GGUF"
    repo.mkdir(parents=True)
    (repo / "m.gguf").write_text("x")
    # LM Studio runs, so its folder is left to its server; Ollama's is not running.
    other = env.folders.lmstudio_models / "google" / "gemma-3-27b-GGUF"
    other.mkdir(parents=True)
    (other / "m.gguf").write_text("x")
    manifest = env.folders.ollama_models / "manifests" / "registry.ollama.ai" / "library"
    (manifest / "gemma3").mkdir(parents=True)
    (manifest / "gemma3" / "4b").write_text("{}")

    found = await env.local.find()

    assert [(m.address, m.model, m.added) for m in found.running] == [
        ("127.0.0.1:1234", "qwen/qwen3-coder-30b", False),
        ("127.0.0.1:1234", "qwen/qwen3-4b", True),
        ("127.0.0.1:9931", "Qwen3-14B-Q4_K_M.gguf", False),
    ]
    assert [(m.name, m.start) for m in found.downloaded] == [("gemma3:4b", None)]


async def test_the_engine_and_the_first_run_choices_are_kept(env: Env) -> None:
    assert await env.local.engine() == "claude"
    await env.local.set_engine("codex")
    assert await env.local.engine() == "codex"
    assert (await env.local.listing()).engine == "codex"

    assert await env.local.setup() == SetupState(first_run=True, local_only=False)
    assert not await env.local.in_use()
    assert await env.local.use_local_only() == SetupState(first_run=False, local_only=True)
    assert await env.local.in_use()
    assert env.bus.ephemeral == [CHANGED, CHANGED]


async def test_there_is_no_first_run_once_done_or_signed_in_or_with_a_model(env: Env) -> None:
    env.signed_in = True
    assert not (await env.local.setup()).first_run
    env.signed_in = False
    env.network.add(mlx())
    await env.local.add("127.0.0.1:8080", None, ["mlx-community/Qwen3-32B-4bit"])
    assert not (await env.local.setup()).first_run
    assert await env.local.in_use()
    await env.local.remove((await env.local.listing()).models[0].id)
    assert (await env.local.setup()).first_run
    assert await env.local.finish_setup() == SetupState(first_run=False, local_only=False)


async def test_apps_are_started_only_when_installed(env: Env) -> None:
    with pytest.raises(AppNotInstalledError):
        await env.local.start("lmstudio")
    with pytest.raises(AppNotInstalledError):
        await env.local.start("ollama")
    env.install_lms()
    env.installed["ollama"] = "/opt/homebrew/bin/ollama"

    await env.local.start("lmstudio")
    await env.local.start("ollama")

    assert env.launched == [
        [str(env.folders.lms), "server", "start"],
        ["/opt/homebrew/bin/ollama", "serve"],
    ]


async def test_starting_forgets_that_a_server_was_down(env: Env) -> None:
    server = env.network.add(ollama())
    await env.local.add("127.0.0.1:11434", None, ["qwen3:32b"])
    env.installed["ollama"] = "/usr/local/bin/ollama"
    server.down = True
    env.clock.advance(timedelta(seconds=5))
    assert not (await env.local.listing()).models[0].running

    server.down = False
    await env.local.start("ollama")

    assert (await env.local.listing()).models[0].running


async def test_launching_detaches_the_command() -> None:
    await launch_detached(["/usr/bin/true"])


async def test_usage_adds_up_for_today_only(env: Env) -> None:
    await env.local.record_usage("lm_a", TokenUsage(input_tokens=10, output_tokens=5))
    await env.local.record_usage(
        "lm_a",
        TokenUsage(
            input_tokens=1,
            output_tokens=2,
            cache_read_input_tokens=3,
            cache_creation_input_tokens=4,
        ),
    )
    await env.local.record_usage("lm_b", TokenUsage(input_tokens=7))

    usage = await env.local.usage()
    assert usage.today_tokens == 32
    assert usage.models == [
        LocalModelUsage(id="lm_a", input_tokens=18, output_tokens=7),
        LocalModelUsage(id="lm_b", input_tokens=7, output_tokens=0),
    ]
    env.clock.advance(timedelta(days=1))
    assert (await env.local.usage()).today_tokens == 0


async def test_checking_a_server_before_a_message_loads_nothing(env: Env) -> None:
    """The message is taken at once; loading waits for the run (B106)."""
    server = env.network.add(lm_studio())
    await env.local.add("127.0.0.1:1234", None, ["qwen/qwen3-4b"])

    await env.local.require_running(local_ref(SMALL))

    assert [r for r in server.requests if r.url.path == "/api/v1/models/load"] == []


async def test_an_lm_studio_model_is_loaded_with_enough_context_for_its_run(env: Env) -> None:
    server = env.network.add(lm_studio())
    await env.local.add("127.0.0.1:1234", None, ["qwen/qwen3-4b"])
    notices: list[str] = []

    async def notice(text: str) -> None:
        notices.append(text)

    await env.local.load_model(local_ref(SMALL), notice)

    loads = [r for r in server.requests if r.url.path == "/api/v1/models/load"]
    assert [r.content for r in loads] == [b'{"model":"qwen/qwen3-4b","context_length":40960}']
    assert notices == ["Loading qwen3-4b in LM Studio"]
    run = await env.local.run_for(local_ref(SMALL))
    assert run.context == 40960
    upstream = await env.local.resolve(LMS)
    assert upstream is not None
    assert (upstream.app, dict(upstream.contexts)) == ("LM Studio", {"qwen/qwen3-4b": 40960})

    # Loaded with enough already: no load and no notice.
    loaded_with(server, "qwen/qwen3-4b", 40960)
    await env.local.load_model(local_ref(SMALL), notice)
    assert notices == ["Loading qwen3-4b in LM Studio"]


def loaded_with(server: ModelServer, model: str, context: int) -> None:
    server.on(
        "GET",
        "/api/v0/models",
        httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": model,
                        "state": "loaded",
                        "max_context_length": context,
                        "loaded_context_length": context,
                    }
                ]
            },
        ),
    )


async def test_a_model_lm_studio_cannot_load_fails_its_turn_with_why(env: Env) -> None:
    server = env.network.add(lm_studio())
    await env.local.add("127.0.0.1:1234", None, ["qwen/qwen3-4b"])
    server.on("POST", "/api/v1/models/load", httpx.Response(500, text="not enough memory"))
    detail = (
        "LM Studio could not load qwen3-4b with enough context for an agent"
        " (not enough memory). Load it in LM Studio, or choose another model."
    )

    async def notice(_text: str) -> None:
        return None

    with pytest.raises(LocalModelNotLoadedError) as raised:
        await env.local.load_model(local_ref(SMALL), notice)

    assert str(raised.value) == detail
    # The failed turn's state says so, once.
    assert await env.local.down(local_ref(SMALL)) == {
        "code": "local_model_not_loaded",
        "detail": detail,
        "app": "LM Studio",
        "address": "127.0.0.1:1234",
        "model": "qwen3-4b",
    }
    assert await env.local.down(local_ref(SMALL)) is None


async def test_other_servers_are_not_asked_to_load(env: Env) -> None:
    server = env.network.add(ollama())
    await env.local.add("127.0.0.1:11434", None, ["qwen3:32b"])

    async def notice(_text: str) -> None:
        raise AssertionError("nothing loads")

    await env.local.load_model(
        local_ref(model_id(server_id("127.0.0.1:11434"), "qwen3:32b")), notice
    )

    assert all(not r.url.path.startswith("/api/v1/") for r in server.requests)


async def test_a_model_too_big_for_this_mac_says_so_when_found_and_added(env: Env) -> None:
    server = env.network.add(lm_studio())
    server.on(
        "GET",
        "/api/v1/models",
        httpx.Response(200, json={"models": [{"key": "qwen/qwen3-coder-30b", "size_bytes": GB12}]}),
    )
    warning = (
        "Needs about 12 GB of this Mac's 24 GB: other work may slow down or the Mac may stall."
    )

    checked = await env.local.check("127.0.0.1:1234", None)
    assert [m.memory_warning for m in checked.models] == [warning, None]
    await env.local.add("127.0.0.1:1234", None, ["qwen/qwen3-coder-30b", "qwen/qwen3-4b"])

    listed = (await env.local.listing()).models
    assert [m.memory_warning for m in listed] == [warning, None]


async def test_a_run_goes_to_the_server_or_the_translator(env: Env) -> None:
    env.network.add(lm_studio())
    env.network.add(llama_cpp())
    await env.local.add("127.0.0.1:1234", None, ["qwen/qwen3-4b"])
    await env.local.add("127.0.0.1:9931", "lk", ["Qwen3-14B-Q4_K_M.gguf"])

    direct = await env.local.run_for(local_ref(SMALL))
    assert (direct.model, direct.context, direct.vision, direct.thinking) == (
        "qwen/qwen3-4b",
        40960,
        True,
        True,
    )
    # Claude always goes through Nest's proxy, even to a server with its own Messages API.
    assert (direct.base_url_for_claude, direct.key_for_claude) == (
        f"http://127.0.0.1:8765/local/{LMS}",
        env.local.translator_key,
    )
    assert (direct.base_url_for_codex, direct.key_for_codex) == (
        "http://127.0.0.1:1234/v1",
        PLACEHOLDER_KEY,
    )

    llama = server_id("127.0.0.1:9931")
    # Only LM Studio counts cache reads in its input tokens.
    assert await env.local.resolve(llama) == Upstream(
        "http://127.0.0.1:9931",
        "lk",
        messages=True,
        usage_counts_cache=False,
        app="llama.cpp",
        contexts={"Qwen3-14B-Q4_K_M.gguf": 32768},
    )
    translated = await env.local.run_for(local_ref(model_id(llama, "Qwen3-14B-Q4_K_M.gguf")))
    assert (translated.base_url_for_claude, translated.key_for_claude) == (
        f"http://127.0.0.1:8765/local/{llama}",
        env.local.translator_key,
    )
    assert (translated.base_url_for_codex, translated.key_for_codex) == (
        f"http://127.0.0.1:8765/local/{llama}/v1",
        env.local.translator_key,
    )

    with pytest.raises(LocalModelNotFoundError):
        await env.local.run_for("local:lm_gone")


async def test_a_server_that_went_away_is_reported(env: Env) -> None:
    server = env.network.add(ollama())
    await env.local.add("127.0.0.1:11434", None, ["qwen3:32b"])
    ref = local_ref(model_id(server_id("127.0.0.1:11434"), "qwen3:32b"))
    await env.local.require_running(ref)
    assert await env.local.down(ref) is None

    server.down = True
    env.installed["ollama"] = "/usr/local/bin/ollama"

    # Asked again at once, whatever the last answer was.
    assert await env.local.down(ref) == {
        "code": "local_server_down",
        "app": "Ollama",
        "address": "127.0.0.1:11434",
        "start": "ollama",
    }
    with pytest.raises(LocalServerDownError) as raised:
        await env.local.require_running(ref)
    assert raised.value.payload()["detail"] == "Ollama at 127.0.0.1:11434 is not running"
    assert await env.local.down("local:lm_gone") is None


async def test_lm_studio_is_offered_to_start_when_its_command_line_exists(env: Env) -> None:
    server = env.network.add(lm_studio())
    await env.local.add("127.0.0.1:1234", None, ["qwen/qwen3-4b"])
    server.down = True
    assert (await env.local.down(local_ref(SMALL)) or {})["start"] is None

    env.install_lms()

    assert (await env.local.down(local_ref(SMALL)) or {})["start"] == "lmstudio"


async def test_the_first_local_model_is_the_default_while_nothing_is_signed_in(env: Env) -> None:
    async def engine_default() -> str | None:
        return "opus"

    assert await env.local.default_or(engine_default) == "opus"
    env.network.add(lm_studio())
    await env.local.add("127.0.0.1:1234", None, ["qwen/qwen3-4b", "qwen/qwen3-coder-30b"])

    assert await env.local.default_or(engine_default) == local_ref(SMALL)
    env.signed_in = True
    assert await env.local.default_or(engine_default) == "opus"


async def test_asks_go_to_a_local_model_when_claude_cannot_take_them(env: Env) -> None:
    assert await env.local.ask_run() is None
    env.network.add(lm_studio())
    await env.local.add("127.0.0.1:1234", None, ["qwen/qwen3-coder-30b"])

    first = await env.local.ask_run()
    assert first is not None
    assert first.model_id == CODER

    env.claude_signed_in = True
    assert await env.local.ask_run() is None
    await env.local.use_local_only()
    assert await env.local.ask_run() is not None


async def test_without_sign_in_sources_nothing_counts_as_signed_in(env: Env) -> None:
    local = LocalModels(
        store=LocalStore(env.db),
        secrets=env.secrets,
        bus=env.bus,
        clock=env.clock,
        port=lambda: 8765,
        setup=LocalSetup(env.folders, env.network.transport()),
    )

    assert (await local.setup()).first_run
    await local.close()


def test_the_default_setup_reaches_the_network_and_the_users_folders(tmp_path: Path) -> None:
    setup = LocalSetup.default(tmp_path, {})

    assert setup.folders == ModelFolders.default(tmp_path, {})
    assert setup.transport is None
    assert setup.launch is launch_detached
