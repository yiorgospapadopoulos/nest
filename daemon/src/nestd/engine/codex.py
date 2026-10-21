"""Codex's model list and login at hand for clients and new chats (B91, D113).

A short-lived app-server is asked when a client or a new chat needs to know and the last
answer is older than `max_age`; its model list is kept in SQLite beside Claude's, so
clients have it after a restart. Codex stays offered when it is not signed in: chats then
fail with `codex_not_signed_in`, which clients show.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from pydantic import BaseModel

from nestd.clock import Clock
from nestd.engine.models import ModelList, engine_default, listed_models
from nestd.engine.store import EngineInfoStore
from nestd.providers.base import AccountInfo, EngineDetails, ModelOption, UsageInfo
from nestd.providers.codex import CodexNotSignedInError
from nestd.providers.codex_engine import DEFAULT_MODEL, CodexDetails, CodexFetchError

logger = logging.getLogger(__name__)

STORE_PREFIX = "codex_"
MAX_AGE = timedelta(minutes=1)


class CodexStatus(BaseModel):
    """`GET /api/providers`' Codex part: whether it can run chats, and who it runs as."""

    # None while Codex could not be asked; `error` then says why, in a word.
    signed_in: bool | None
    checked_at: datetime
    account: AccountInfo | None = None
    error: str | None = None


class CodexEngine:
    def __init__(
        self,
        store: EngineInfoStore,
        fetch: Callable[[], Awaitable[CodexDetails]],
        clock: Clock,
        fetch_usage: Callable[[], Awaitable[UsageInfo | None]],
        max_age: timedelta = MAX_AGE,
        on_signed_in: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """`on_signed_in` hears of every answer saying Codex is signed in (B94)."""
        self._store = store
        self._fetch = fetch
        self._fetch_usage = fetch_usage
        self._clock = clock
        self._max_age = max_age
        self._on_signed_in = on_signed_in
        self._lock = asyncio.Lock()
        self._status: CodexStatus | None = None

    async def status(self, refresh: bool = False) -> CodexStatus:
        """The last answer while it is fresh; else Codex is asked again."""
        async with self._lock:
            status = self._status
            now = self._clock.now()
            if not refresh and status is not None and now - status.checked_at < self._max_age:
                return status
            self._status = await self._ask(now)
            return self._status

    def forget(self) -> None:
        """Ask Codex again next time: the active account changed (B98)."""
        self._status = None

    async def require_signed_in(self) -> None:
        """409 `codex_not_signed_in` when Codex said it has no login; a Codex that could
        not be asked is left to fail on its own when the chat starts.
        """
        if (await self.status()).signed_in is False:
            raise CodexNotSignedInError

    async def models(self) -> ModelList:
        """Codex's last reported list, real models only with its default named (B94);
        asked once when none is kept, else empty.
        """
        listed = await self._store.models()
        if listed is None:
            await self.status()
            listed = await self._store.models()
        return listed_models(listed or ModelList(models=[], updated_at=None))

    async def default_model(self) -> str | None:
        """The concrete model Codex runs when none is named; None before it reported."""
        listed = await self._store.models()
        return None if listed is None else engine_default(listed.models)

    async def account(self) -> AccountInfo:
        return (await self.status()).account or AccountInfo()

    async def find(self, model: str | None) -> ModelOption | None:
        """The listed entry for `model` (None is Codex's default); None while unknown."""
        listed = await self._store.models()
        if listed is None:
            return None
        value = model or DEFAULT_MODEL
        return next((option for option in listed.models if option.value == value), None)

    async def usage(self) -> UsageInfo | None:
        """Codex's usage windows now (B91); None while it is not signed in or could not say.
        Reads the account only, never runs a model.
        """
        if (await self.status()).signed_in is not True:
            return None
        try:
            return await self._fetch_usage()
        except CodexFetchError as error:
            logger.warning("could not ask Codex for its usage: %s", error)
            return None

    async def _ask(self, now: datetime) -> CodexStatus:
        try:
            details = await self._fetch()
        except CodexFetchError as error:
            logger.warning("could not ask Codex for its models and login: %s", error)
            return CodexStatus(signed_in=None, checked_at=now, error=str(error))
        await self._store.save(EngineDetails(models=details.models, account=details.login.account))
        if details.login.signed_in and self._on_signed_in is not None:
            await self._on_signed_in()
        return CodexStatus(
            signed_in=details.login.signed_in, account=details.login.account, checked_at=now
        )
