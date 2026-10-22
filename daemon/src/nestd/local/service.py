"""Local models (B106): servers added like accounts, their models in every model menu.

A chat on a local model still runs on Claude Code (the default) or Codex, pointed at the
server for that run (`run`). Whether a server answers is asked again after a few seconds
at most. A server's key lives in the Keychain only. Nest starts LM Studio's server or
Ollama when asked, never installs anything.
"""

import asyncio
import shutil
import subprocess
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from secrets import token_urlsafe
from typing import Self

import httpx
from pydantic import JsonValue

from nestd.auth.secrets import SecretStore
from nestd.clock import Clock
from nestd.errors import InvalidInputError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.local.discovery import ModelFolders, Which, display_name, downloaded, found_models
from nestd.local.discovery import running as running_servers
from nestd.local.errors import (
    AppNotInstalledError,
    LocalModelNotFoundError,
    LocalModelNotLoadedError,
    LocalServerDownError,
)
from nestd.local.loading import LoadError, ensure_loaded
from nestd.local.memory import mac_memory, memory_warning
from nestd.local.models import (
    CheckResult,
    FoundModel,
    FoundModels,
    LocalEngine,
    LocalModel,
    LocalModelList,
    LocalModelUsage,
    LocalServerInfo,
    LocalUsage,
    SetupState,
    StartApp,
    local_id,
    local_ref,
)
from nestd.local.probe import ProbedServer, normalise, probe, reachable
from nestd.local.run import LocalRun, RunServer, local_run
from nestd.local.store import LocalStore, StoredModel, StoredServer, model_id, server_id
from nestd.local.translate.upstream import Upstream
from nestd.providers.base import TokenUsage

# How long a server's answer to "are you there" holds.
CHECK_TTL = timedelta(seconds=3)
ENGINE = "local_engine"
LOCAL_ONLY = "local_only"
FIRST_RUN_DONE = "first_run_done"
_APPS: dict[str, StartApp] = {"LM Studio": "lmstudio", "Ollama": "ollama"}
# The app whose Messages usage counts cache reads inside input_tokens (live, 0.4.21).
_LM_STUDIO = "LM Studio"

type Launch = Callable[[Sequence[str]], Awaitable[None]]
type SignedIn = Callable[[], Awaitable[bool]]
type DefaultModel = Callable[[], Awaitable[str | None]]


async def launch_detached(command: Sequence[str]) -> None:
    """Through a shell that exits at once: the server runs on in its own session, and the
    daemon waits for nothing.
    """
    await asyncio.to_thread(
        subprocess.run,
        ["/bin/sh", "-c", '"$@" >/dev/null 2>&1 &', "nest-start", *command],
        check=True,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


@dataclass(frozen=True)
class LocalSetup:
    """What the local models reach on this Mac; tests replace each part."""

    folders: ModelFolders
    # None is the network.
    transport: httpx.AsyncBaseTransport | None = None
    which: Which = shutil.which
    launch: Launch = launch_detached
    # This Mac's memory in bytes, for the memory warning.
    memory: Callable[[], int | None] = mac_memory

    @classmethod
    def default(cls, home: Path, env: Mapping[str, str]) -> Self:
        return cls(ModelFolders.default(home, env))


async def _never() -> bool:
    return False


def key_account(server: str) -> str:
    """The server's Keychain item."""
    return f"local-server:{server}"


class LocalModels:
    def __init__(
        self,
        *,
        store: LocalStore,
        secrets: SecretStore,
        bus: EventBus,
        clock: Clock,
        port: Callable[[], int],
        setup: LocalSetup,
        zone: tzinfo | None = None,
        signed_in: SignedIn = _never,
        claude_signed_in: SignedIn = _never,
    ) -> None:
        """`port` is the daemon's, where the translator listens. `signed_in` says whether
        any engine is signed in, and `claude_signed_in` whether Claude is.
        """
        self._store = store
        self._secrets = secrets
        self._bus = bus
        self._clock = clock
        self._port = port
        self._folders = setup.folders
        self._which = setup.which
        self._launch = setup.launch
        self._memory = setup.memory
        self._zone = zone
        self._signed_in = signed_in
        self._claude_signed_in = claude_signed_in
        self._client = httpx.AsyncClient(transport=setup.transport)
        # The translator reaches the servers the same way.
        self.transport = setup.transport
        # The engines send it to the translator; made for this daemon's life only.
        self.translator_key = token_urlsafe(32)
        self._targets: dict[str, Upstream] = {}
        self._checked: dict[str, tuple[datetime, bool]] = {}
        # The context LM Studio loaded each model with for Nest, by local model id.
        self._loaded: dict[str, int] = {}
        # Why each model's last load failed, until its failed turn reports it.
        self._failed: dict[str, dict[str, JsonValue]] = {}

    async def load(self) -> None:
        """Read the servers for `resolve`."""
        for server in await self._store.servers():
            self._targets[server.id] = self._upstream(server)

    async def close(self) -> None:
        await self._client.aclose()

    async def resolve(self, server: str) -> Upstream | None:
        """For the proxy: the server's base URL, key, whether it speaks Anthropic Messages
        itself, its app and its models' contexts; None for an unknown one."""
        found = self._targets.get(server)
        if found is None:
            return None
        contexts = {
            model.model: context
            for model in await self._store.models()
            if model.server_id == server and (context := self._context(model)) is not None
        }
        return replace(found, contexts=contexts)

    def _upstream(self, server: StoredServer) -> Upstream:
        return Upstream(
            server.base_url,
            self._key(server),
            messages=server.has_messages,
            usage_counts_cache=server.app == _LM_STUDIO,
            app=server.app,
        )

    # Listing and adding

    async def listing(self) -> LocalModelList:
        servers = {server.id: server for server in await self._store.servers()}
        running = dict(
            zip(
                servers,
                await asyncio.gather(*(self._running(server) for server in servers.values())),
                strict=True,
            )
        )
        memory = self._memory()
        return LocalModelList(
            models=[
                _view(model, servers[model.server_id], running[model.server_id], memory)
                for model in await self._store.models()
            ],
            engine=await self.engine(),
            local_only=await self._flag(LOCAL_ONLY),
        )

    async def find(self) -> FoundModels:
        """Servers running on this Mac's usual ports, and the models downloaded on it."""
        added = await self._added()
        servers = await running_servers(self._client)
        memory = self._memory()
        found = [model for server in servers for model in found_models(server, added, memory)]
        served = {model.model for model in found}
        apps = {server.app for server in servers}
        on_disk = await asyncio.to_thread(downloaded, self._folders, self._which, served, apps)
        return FoundModels(running=found, downloaded=on_disk)

    async def check(self, address: str, key: str | None) -> CheckResult:
        where = normalise(address)
        known = await self._store.server(server_id(where.address))
        server = await probe(self._client, where, self._given_or_stored(key, known))
        if server is None:
            return CheckResult(ok=False, error="unreachable", server=None, models=[])
        info = LocalServerInfo(
            address=where.address,
            app=server.app,
            messages=server.messages,
            responses=server.responses,
            chat=server.chat,
        )
        models = found_models(server, await self._added(), self._memory())
        error = (
            "no_models"
            if not models
            else "no_tools"
            if all(model.tools == "none" for model in models)
            else None
        )
        return CheckResult(ok=error is None, error=error, server=info, models=models)

    async def add(self, address: str, key: str | None, models: list[str]) -> list[LocalModel]:
        """Store the server and the chosen models it serves; 422 for one it does not."""
        where = normalise(address)
        sid = server_id(where.address)
        known = await self._store.server(sid)
        key = key or None
        server = await probe(self._client, where, self._given_or_stored(key, known))
        if server is None:
            raise LocalServerDownError({"app": None, "address": where.address, "start": None})
        offered = {found.model: found for found in found_models(server, ())}
        sizes = {model.model: model.size for model in server.models}
        missing = [name for name in models if name not in offered]
        if missing:
            msg = f"{where.address} does not serve {', '.join(missing)}"
            raise InvalidInputError(msg)
        if key is not None:
            self._secrets.set(key_account(sid), key)
        has_key = key is not None or (known is not None and known.has_key)
        stored = _stored_server(server, sid, self._clock.now(), has_key)
        await self._store.save_server(stored)
        for name in models:
            stored_model = _stored_model(offered[name], sid, sizes[name], self._clock.now())
            await self._store.add_model(stored_model)
        self._targets[sid] = self._upstream(stored)
        self._checked[sid] = (self._clock.now(), True)
        await self._changed()
        wanted = {model_id(sid, name) for name in models}
        return [model for model in (await self.listing()).models if model.id in wanted]

    async def remove(self, model: str) -> None:
        """404 for an unknown model. A server left without models goes, with its key."""
        stored = await self._store.model(model)
        if stored is None:
            raise LocalModelNotFoundError(model)
        await self._store.remove_model(model)
        if not any(other.server_id == stored.server_id for other in await self._store.models()):
            await self._store.remove_server(stored.server_id)
            self._secrets.delete(key_account(stored.server_id))
            self._targets.pop(stored.server_id, None)
            self._checked.pop(stored.server_id, None)
        await self._changed()

    # Settings

    async def engine(self) -> LocalEngine:
        return "codex" if await self._store.setting(ENGINE) == "codex" else "claude"

    async def set_engine(self, engine: LocalEngine) -> None:
        await self._store.set_setting(ENGINE, engine)
        await self._changed()

    async def setup(self) -> SetupState:
        """The first run: nothing signed in, no local model, and the user has not chosen."""
        first = (
            not await self._flag(FIRST_RUN_DONE)
            and not await self._store.models()
            and not await self._signed_in()
        )
        return SetupState(first_run=first, local_only=await self._flag(LOCAL_ONLY))

    async def use_local_only(self) -> SetupState:
        await self._store.set_setting(LOCAL_ONLY, True)
        await self._store.set_setting(FIRST_RUN_DONE, True)
        await self._changed()
        return await self.setup()

    async def finish_setup(self) -> SetupState:
        await self._store.set_setting(FIRST_RUN_DONE, True)
        return await self.setup()

    async def in_use(self) -> bool:
        """Local models exist, or the user chose to use only them."""
        return await self._flag(LOCAL_ONLY) or bool(await self._store.models())

    # Servers

    async def start(self, app: StartApp) -> None:
        """Start LM Studio's server or Ollama; 404 when the app is not installed."""
        if app == "lmstudio":
            lms = self._folders.lms
            if not lms.is_file():
                raise AppNotInstalledError("LM Studio's command line is not installed")
            await self._launch([str(lms), "server", "start"])
        else:
            ollama = self._which("ollama")
            if ollama is None:
                raise AppNotInstalledError("Ollama is not installed")
            await self._launch([ollama, "serve"])
        self._checked.clear()

    # Usage

    async def record_usage(self, model: str, tokens: TokenUsage) -> None:
        """A local turn's tokens, for today; cached input counts as input."""
        read = tokens.input_tokens + tokens.cache_read_input_tokens
        await self._store.add_usage(
            self._today(), model, read + tokens.cache_creation_input_tokens, tokens.output_tokens
        )

    async def usage(self) -> LocalUsage:
        rows = await self._store.usage(self._today())
        return LocalUsage(
            today_tokens=sum(given + made for _, given, made in rows),
            models=[
                LocalModelUsage(id=model, input_tokens=given, output_tokens=made)
                for model, given, made in rows
            ],
        )

    # What sessions and the rest of Nest ask

    async def run_for(self, model: str) -> LocalRun:
        """Where a run on the `local:` model goes; 404 for one removed since."""
        stored, server = await self._model(model)
        return local_run(
            RunServer(
                id=server.id,
                base_url=server.base_url,
                has_responses=server.has_responses,
                key=self._key(server),
            ),
            model_id=stored.id,
            model=stored.model,
            context=self._context(stored),
            vision=stored.vision,
            thinking=stored.thinking,
            port=self._port(),
            translator_key=self.translator_key,
        )

    async def require_running(self, model: str) -> None:
        """409 `local_server_down` when the model's server does not answer (cached a few
        seconds, so a message is taken at once).
        """
        _, server = await self._model(model)
        if not await self._running(server):
            raise LocalServerDownError(self._down(server))

    async def load_model(self, model: str, notice: Callable[[str], Awaitable[None]]) -> None:
        """When its run opens, LM Studio is made to load the model with the context an
        agent needs; `notice` hears it in words when a load starts. Raises
        `LocalModelNotLoadedError` when LM Studio cannot, which the failed turn then
        reports (`down`).
        """
        stored, server = await self._model(model)
        if server.app != _LM_STUDIO:
            return

        async def loading() -> None:
            await notice(f"Loading {stored.name} in LM Studio")

        self._failed.pop(stored.id, None)
        try:
            self._loaded[stored.id] = await ensure_loaded(
                self._client, server.base_url, self._key(server), stored.model, loading
            )
        except LoadError as error:
            details: dict[str, JsonValue] = {
                "app": server.app,
                "address": server.address,
                "model": stored.name,
            }
            failure = LocalModelNotLoadedError(details, str(error))
            self._failed[stored.id] = failure.state_details()
            raise failure from error

    async def down(self, model: str) -> dict[str, JsonValue] | None:
        """What a failed turn's clients show: that its model could not be loaded, else
        whether the server went away, asked now.
        """
        try:
            stored, server = await self._model(model)
        except LocalModelNotFoundError:
            return None
        failed = self._failed.pop(stored.id, None)
        if failed is not None:
            return failed
        self._checked.pop(server.id, None)
        if await self._running(server):
            return None
        return {"code": LocalServerDownError.code, **self._down(server)}

    async def engine_signed_in(self) -> bool:
        """Whether any engine is signed in; without one, defaults are only provisional."""
        return await self._signed_in()

    async def default_or(self, default: DefaultModel) -> str | None:
        """The engine's default model, or the first local model while no engine is
        signed in.
        """
        models = await self._store.models()
        if models and not await self._signed_in():
            return local_ref(models[0].id)
        return await default()

    async def ask_run(self) -> LocalRun | None:
        """Where artifact asks go when Claude cannot take them: the first local model."""
        models = await self._store.models()
        if not models:
            return None
        if not await self._flag(LOCAL_ONLY) and await self._claude_signed_in():
            return None
        return await self.run_for(local_ref(models[0].id))

    # Helpers

    async def _model(self, model: str) -> tuple[StoredModel, StoredServer]:
        stored = await self._store.model(local_id(model))
        server = None if stored is None else await self._store.server(stored.server_id)
        if stored is None or server is None:
            raise LocalModelNotFoundError(local_id(model))
        return stored, server

    async def _running(self, server: StoredServer) -> bool:
        now = self._clock.now()
        checked = self._checked.get(server.id)
        if checked is not None and now - checked[0] < CHECK_TTL:
            return checked[1]
        answer = await reachable(self._client, server.base_url, self._key(server))
        self._checked[server.id] = (now, answer)
        return answer

    def _context(self, model: StoredModel) -> int | None:
        """The context it runs with: what Nest had LM Studio load it with, else as found."""
        return self._loaded.get(model.id, model.context)

    def _down(self, server: StoredServer) -> dict[str, JsonValue]:
        return {"app": server.app, "address": server.address, "start": self._start_for(server.app)}

    def _start_for(self, app: str | None) -> StartApp | None:
        start = None if app is None else _APPS.get(app)
        if start == "lmstudio" and self._folders.lms.is_file():
            return start
        if start == "ollama" and self._which("ollama") is not None:
            return start
        return None

    def _given_or_stored(self, key: str | None, known: StoredServer | None) -> str | None:
        return key or (None if known is None else self._key(known))

    def _key(self, server: StoredServer) -> str | None:
        return self._secrets.get(key_account(server.id)) if server.has_key else None

    async def _added(self) -> set[tuple[str, str]]:
        servers = {server.id: server.address for server in await self._store.servers()}
        return {(servers[model.server_id], model.model) for model in await self._store.models()}

    async def _flag(self, name: str) -> bool:
        return await self._store.setting(name) is True

    def _today(self) -> str:
        return self._clock.now().astimezone(self._zone).date().isoformat()

    async def _changed(self) -> None:
        await self._bus.publish_ephemeral(types.LOCAL_MODELS_CHANGED, {})


def _stored_server(server: ProbedServer, sid: str, now: datetime, has_key: bool) -> StoredServer:
    return StoredServer(
        id=sid,
        address=server.address.address,
        base_url=server.address.base_url,
        app=server.app,
        has_messages=server.messages,
        has_responses=server.responses,
        has_chat=server.chat,
        has_key=has_key,
        checked_at=now,
    )


def _stored_model(found: FoundModel, sid: str, size: int | None, now: datetime) -> StoredModel:
    return StoredModel(
        id=model_id(sid, found.model),
        server_id=sid,
        model=found.model,
        name=display_name(found.model),
        context=found.context,
        tools=found.tools,
        weak_reason=found.weak_reason,
        vision=found.vision,
        thinking=found.thinking,
        size=size,
        position=0,
        added_at=now,
    )


def _view(
    model: StoredModel, server: StoredServer, running: bool, memory: int | None
) -> LocalModel:
    return LocalModel(
        id=model.id,
        server_id=server.id,
        model=model.model,
        name=model.name,
        address=server.address,
        app=server.app,
        context=model.context,
        tools=model.tools,
        weak_reason=model.weak_reason,
        vision=model.vision,
        thinking=model.thinking,
        running=running,
        has_key=server.has_key,
        memory_warning=memory_warning(model.size, memory),
    )
