"""An ACP engine at hand for clients and new chats (B107): installed or not, signed in or
not, its models, and how its process starts.

Like Codex's (`engine/codex.py`), the model list comes from a short engine run, here in a
scratch folder of Nest's (`<data_dir>/engines/<id>/probe/`), asked at most once a minute
and kept in SQLite under the engine's prefix. Whether it is signed in needs no run for two
of them: OpenCode is signed in when its own login file holds an entry (it answers ACP
signed out, on its free models), and Gemini when Nest has its API key. The others say so
when a session is started (`auth_required`).

The API key lives only in the Keychain (`engine-key:<account id>`) and in the engine
process's environment: never in a file, a log, an event or an answer.
"""

import asyncio
import json
import logging
import os
import shlex
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from pydantic import BaseModel

from nestd.auth.secrets import SecretStore
from nestd.clock import Clock
from nestd.engine.acp_install import (
    CONFIG_FOLDER,
    PROBE_FOLDER,
    EngineInstall,
    EngineState,
    InstallState,
    NpmRunner,
    run_npm,
)
from nestd.engine.acp_registry import platform_name
from nestd.engine.cursor_config import CONFIG_DIR_ENV, user_config_dir, write_config
from nestd.engine.models import ENGINE_DEFAULT, ModelList, engine_default, listed_models
from nestd.engine.opencode_local import is_local_model, local_providers
from nestd.engine.store import EngineInfoStore
from nestd.providers.acp import AcpNotReadyError, AcpProbe, probe
from nestd.providers.acp_engines import (
    ACP_ENGINES,
    GEMINI_KEY_ENV,
    GEMINI_SYSTEM_SETTINGS,
    GEMINI_SYSTEM_SETTINGS_ENV,
    AcpEngine,
)
from nestd.providers.acp_process import AcpLaunch, AcpTransportFactory, spawn_acp
from nestd.providers.base import EngineDetails, ModelOption, RunAccount
from nestd.providers.shell_env import ShellEnvSource
from nestd.storage.db import Database
from nestd.usage.store import first_account

logger = logging.getLogger(__name__)

MAX_AGE = timedelta(minutes=1)
SETTINGS_FILE = "system-settings.json"
# The key variables an engine reads; an added account never gets the user's own.
_KEY_ENV = {"gemini": GEMINI_KEY_ENV}
_INHERITED_KEYS = {"gemini": (GEMINI_KEY_ENV, "GOOGLE_API_KEY")}


@dataclass(frozen=True)
class AcpSetup:
    """What the ACP engines reach outside Nest, replaced in tests (B107)."""

    npm: NpmRunner = run_npm
    transport: AcpTransportFactory = spawn_acp
    # The environment engines and npm start from; None is the daemon's.
    base_env: Mapping[str, str] | None = None
    # Where `~` in a user install's path points; None is the user's home.
    home: Path | None = None


def build_acp_engines(
    *,
    root: Path,
    db: Database,
    clock: Clock,
    secrets: SecretStore,
    shell_env: ShellEnvSource,
    active: Callable[[str], Awaitable[RunAccount]],
    on_change: Callable[[AcpEngine, InstallState], Awaitable[None]] | None,
    setup: AcpSetup,
    environments: Path | None = None,
) -> dict[str, "AcpEngineService"]:
    """One service per engine Nest runs, in the catalogue's order; `root` is
    `<data_dir>/engines`, `active` gives an engine's active account, and `environments`
    holds the prepared environments, whose engine versions stay.
    """
    base = os.environ if setup.base_env is None else setup.base_env

    async def env() -> Mapping[str, str]:
        return {**base, **await shell_env()}

    services: dict[str, AcpEngineService] = {}
    for engine in ACP_ENGINES:

        async def changed(state: InstallState, engine: AcpEngine = engine) -> None:
            services[engine.id].forget()
            if on_change is not None:
                await on_change(engine, state)

        async def account(engine: AcpEngine = engine) -> RunAccount:
            return await active(engine.id)

        install = EngineInstall(
            engine,
            root,
            setup.npm,
            env,
            setup.home or Path.home(),
            on_change=changed,
            environments=environments,
        )
        services[engine.id] = AcpEngineService(
            engine,
            install,
            EngineInfoStore(db, clock, f"{engine.id}_"),
            secrets,
            clock,
            env,
            account,
            setup.transport,
        )
    return services


def key_item(account_id: str) -> str:
    """The Keychain item of an account's API key."""
    return f"engine-key:{account_id}"


class AcpStatus(BaseModel):
    """The engine's part of `GET /api/providers`."""

    state: EngineState
    version: str | None
    state_detail: str | None
    # None while it is not installed, or its sign in could not be asked.
    signed_in: bool | None
    # The command that signs in in Terminal, when the engine has one.
    login_command: str | None
    checked_at: datetime


class AcpAccountStatus(BaseModel):
    """One account of the engine, as Settings > Accounts shows it."""

    signed_in: bool | None
    email: str | None = None
    plan: str | None = None
    checked_at: datetime
    error: str | None = None


class AcpEngineService:
    def __init__(
        self,
        engine: AcpEngine,
        install: EngineInstall,
        store: EngineInfoStore,
        secrets: SecretStore,
        clock: Clock,
        env: Callable[[], Awaitable[Mapping[str, str]]],
        active: Callable[[], Awaitable[RunAccount]],
        transport: AcpTransportFactory,
        max_age: timedelta = MAX_AGE,
    ) -> None:
        """`env` is the daemon's environment with the login shell's over it; `active`
        the engine's active account, made ready to run on.
        """
        self.engine = engine
        self.install = install
        self._store = store
        self._secrets = secrets
        self._clock = clock
        self._env = env
        self._active = active
        self._transport = transport
        self._max_age = max_age
        self._lock = asyncio.Lock()
        self._status: AcpStatus | None = None
        # The version the user's own install reported (`user_install`).
        self._reported_version: str | None = None

    @property
    def name(self) -> str:
        return self.engine.id

    async def status(self, refresh: bool = False) -> AcpStatus:
        """The last answer while it is fresh and the install did not change; else the
        engine is asked again.
        """
        async with self._lock:
            installed = await self.install.current()
            status = self._status
            now = self._clock.now()
            if (
                not refresh
                and status is not None
                and status.state == installed.state
                and now - status.checked_at < self._max_age
            ):
                return status
            self._status = await self._ask(installed, await self._active(), now)
            return self._status

    def forget(self) -> None:
        """Ask again next time: the active account, its key or the install changed."""
        self._status = None

    async def require_ready(self) -> None:
        """409 `engine_not_ready` unless a chat can start now. A missing pinned engine
        starts installing in the background (first use).
        """
        installed = await self.install.current()
        self._require_installed(installed)
        account = await self._active()
        if self.engine.sign_in == "api_key" and await self._key(account) is None:
            raise AcpNotReadyError(self._no_key())
        if self.engine.auth_file is not None:
            if not await self._logged_in(account, self.engine.auth_file):
                raise AcpNotReadyError(self._signed_out())
        elif self.engine.sign_in == "terminal":
            known = self._status
            if known is None or known.state != "ready":
                known = await self.status()
            if known.signed_in is False:
                raise AcpNotReadyError(self._signed_out())

    async def models(self) -> ModelList:
        """The last reported list, real models only with the default named; asked once
        when none is kept, else empty.
        """
        listed = await self._store.models()
        if listed is None:
            await self.status()
            listed = await self._store.models()
        served = listed_models(listed or ModelList(models=[], updated_at=None))
        return await self._marked_local(served) if self.engine.id == "opencode" else served

    async def _marked_local(self, listed: ModelList) -> ModelList:
        """OpenCode's list with the models of the user's own servers marked."""
        env = await self._env()
        config = env.get("XDG_CONFIG_HOME") or str(self.install.home / ".config")
        providers = await asyncio.to_thread(local_providers, Path(config) / "opencode")
        models = [
            model.model_copy(update={"local": is_local_model(model.value, providers)})
            for model in listed.models
        ]
        return listed.model_copy(update={"models": models})

    async def find(self, model: str | None) -> ModelOption | None:
        listed = await self._store.models()
        if listed is None:
            return None
        value = model or ENGINE_DEFAULT
        return next((option for option in listed.models if option.value == value), None)

    async def default_model(self) -> str | None:
        listed = await self._store.models()
        return None if listed is None else engine_default(listed.models)

    async def launch(self, account: RunAccount | None) -> AcpLaunch:
        """How the engine's process starts on `account` (None: the first account): its
        program, Nest's settings for it and the account's folder and key. 409 when it
        cannot start.
        """
        installed = await self.install.current()
        program = self._require_installed(installed)
        account = account or RunAccount(first_account(self.engine.id))
        env = await self._launch_env(account)
        if self.engine.sign_in == "api_key":
            key = await self._key(account, env)
            if key is None:
                raise AcpNotReadyError(self._no_key())
            env[_KEY_ENV[self.engine.id]] = key
        pinned = self.engine.downloads.get(platform_name())
        extra = pinned.args if pinned is not None else ()
        return AcpLaunch(args=(str(program), *self.engine.args, *extra), env=env)

    async def account_status(self, account: RunAccount) -> AcpAccountStatus:
        """Whether that account can run chats: asked of the engine only for a terminal
        sign in without a login file, and only once it is installed.
        """
        now = self._clock.now()
        installed = await self.install.current()
        if self.engine.sign_in == "api_key":
            return AcpAccountStatus(signed_in=await self._key(account) is not None, checked_at=now)
        if installed.state != "ready":
            return AcpAccountStatus(signed_in=None, checked_at=now, error=installed.detail)
        if account.id == (await self._active()).id:
            status = await self.status(refresh=True)
            return AcpAccountStatus(signed_in=status.signed_in, checked_at=now)
        if self.engine.auth_file is not None:
            return AcpAccountStatus(
                signed_in=await self._logged_in(account, self.engine.auth_file), checked_at=now
            )
        found = await self._probe(account)
        return AcpAccountStatus(
            signed_in=None if found is None else found.signed_in,
            checked_at=now,
            error=None if found is not None else "could not be asked",
        )

    async def login_command(self, account: RunAccount) -> str | None:
        """The command that signs the account in, in Terminal: the engine Nest runs, on
        the account's folder.
        """
        installed = await self.install.current()
        if self.engine.login_method is not None:
            if installed.program is None:
                return None
            nestd = (sys.executable, "-m", "nestd", "engines", "sign-in", self.engine.id)
            words = [*nestd, str(installed.program)]
        elif self.engine.login_command is None:
            return None
        else:
            words = shlex.split(self.engine.login_command)
            if installed.program is not None:
                words[0] = str(installed.program)
        assignments = [f"{name}={shlex.quote(value)}" for name, value in account.env.items()]
        return " ".join([*assignments, *(shlex.quote(word) for word in words)])

    def has_key(self, account_id: str) -> bool:
        """Whether Nest keeps a key for the account (the user's shell's is not counted)."""
        return self._secrets.get(key_item(account_id)) is not None

    def set_key(self, account_id: str, key: str) -> None:
        self._secrets.set(key_item(account_id), key)
        self.forget()

    def delete_key(self, account_id: str) -> None:
        self._secrets.delete(key_item(account_id))
        self.forget()

    async def _ask(self, installed: InstallState, account: RunAccount, now: datetime) -> AcpStatus:
        signed_in: bool | None = None
        version = installed.version
        if self.engine.sign_in == "api_key":
            signed_in = await self._key(account) is not None
        elif self.engine.auth_file is not None and installed.state == "ready":
            signed_in = await self._logged_in(account, self.engine.auth_file)
        if installed.state == "ready" and signed_in is not False:
            found = await self._probe(account)
            if found is not None:
                await self._store.save(EngineDetails(models=found.models))
                if found.agent_version is not None and self.engine.version is None:
                    self._reported_version = found.agent_version
                if self.engine.sign_in == "terminal" and self.engine.auth_file is None:
                    signed_in = found.signed_in
        if self.engine.delivery == "user_install" and installed.state == "ready":
            version = self._reported_version
        return AcpStatus(
            state=installed.state,
            version=version,
            state_detail=installed.detail,
            signed_in=signed_in,
            login_command=await self.login_command(account),
            checked_at=now,
        )

    async def _probe(self, account: RunAccount) -> AcpProbe | None:
        """A short run in Nest's scratch folder; None when it could not be asked."""
        folder = self.install.folder / PROBE_FOLDER
        try:
            launch = await self.launch(account)
            launch = replace(launch, env={**launch.env, **self.engine.probe_env})
            await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
            return await probe(launch, folder, self._transport)
        except AcpNotReadyError:
            return None
        except Exception as error:
            # Only the kind of failure: an engine's own message may quote its environment.
            logger.warning(
                "could not ask %s for its models: %s", self.engine.id, type(error).__name__
            )
            return None

    async def _logged_in(self, account: RunAccount, auth_file: str) -> bool:
        """Whether the engine's login file for the account holds an entry, under the
        account's folder for it (`auth_root`), else the user's, else the default one in
        the home.
        """
        env = {**await self._env(), **account.env}
        variable, default = self.engine.auth_root
        root = env.get(variable) or str(self.install.home / default)
        return await asyncio.to_thread(_holds_entries, Path(root) / auth_file)

    def _require_installed(self, installed: InstallState) -> Path:
        if installed.state == "ready" and installed.program is not None:
            return installed.program
        name = self.engine.name
        if installed.state == "installing" or self.install.start():
            msg = f"{name} is being installed. Try again in a moment."
        elif installed.state == "install_failed":
            msg = f"{name} could not be installed: {installed.detail}"
        else:
            msg = installed.detail or f"{name} is not installed."
        raise AcpNotReadyError(msg)

    async def _launch_env(self, account: RunAccount) -> dict[str, str]:
        env = dict(await self._env())
        if account.id != first_account(self.engine.id):
            for name in _INHERITED_KEYS.get(self.engine.id, ()):
                env.pop(name, None)
        env.update(account.env)
        env.update(self.engine.env)
        if self.engine.id == "gemini":
            env[GEMINI_SYSTEM_SETTINGS_ENV] = str(await asyncio.to_thread(self._settings_file))
        if self.engine.id == "cursor":
            user = user_config_dir(env, self.install.home)
            folder = self.install.folder / CONFIG_FOLDER
            env[CONFIG_DIR_ENV] = str(await asyncio.to_thread(write_config, folder, user))
        return env

    def _settings_file(self) -> Path:
        """Nest's system settings for Gemini, beside its versions: they win over the
        user's and the project's, so every call is asked.
        """
        path = self.install.folder / SETTINGS_FILE
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            current = None
        if current is None or json.loads(current or "null") != json.loads(GEMINI_SYSTEM_SETTINGS):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(GEMINI_SYSTEM_SETTINGS, encoding="utf-8")
        return path

    async def _key(self, account: RunAccount, env: Mapping[str, str] | None = None) -> str | None:
        """Nest's key for the account; for the first account, else the one the user's
        shell exports.
        """
        stored = await asyncio.to_thread(self._secrets.get, key_item(account.id))
        if stored:
            return stored
        if account.id != first_account(self.engine.id):
            return None
        name = _KEY_ENV.get(self.engine.id)
        source = env if env is not None else await self._env()
        return None if name is None else source.get(name) or None

    def _no_key(self) -> str:
        return f"Add your {self.engine.name} API key in Settings > Accounts."

    def _signed_out(self) -> str:
        if self.engine.login_command is None:
            return f"{self.engine.name} is not signed in. Sign in in Settings > Accounts."
        command = self.engine.login_command
        return f"{self.engine.name} is not signed in. Sign in with `{command}` in Terminal."


def _holds_entries(path: Path) -> bool:
    """Whether a JSON login file holds at least one entry; missing, empty or unreadable is
    signed out. Only its keys are looked at: the values are secrets.
    """
    try:
        found: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(found, dict) and len(cast("dict[str, object]", found)) > 0
