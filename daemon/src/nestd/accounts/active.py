"""The account each engine uses now (B98), at hand for every turn's start."""

import asyncio
from collections.abc import Mapping

from nestd.accounts.profiles import Profiles
from nestd.accounts.store import AccountStore, StoredAccount
from nestd.errors import NotFoundError
from nestd.providers.base import RunAccount
from nestd.usage.store import first_account


async def run_account(profiles: Profiles, account: StoredAccount) -> RunAccount:
    """The account ready for a new engine process: an added one's profile folder is made
    and its shared setup brought up to date.
    """
    if account.profile is None:
        return RunAccount(account.id)
    env = await asyncio.to_thread(profiles.prepare, account.provider, account.profile)
    return RunAccount(account.id, env)


class ActiveAccounts:
    def __init__(self, profiles: Profiles, chosen: Mapping[str, StoredAccount]) -> None:
        self._profiles = profiles
        self._chosen = dict(chosen)

    @classmethod
    async def load(cls, store: AccountStore, profiles: Profiles) -> "ActiveAccounts":
        chosen: dict[str, StoredAccount] = {}
        for provider, account_id in (await store.active()).items():
            try:
                chosen[provider] = await store.get(account_id)
            except NotFoundError:
                continue
        return cls(profiles, chosen)

    def id(self, provider: str) -> str:
        account = self._chosen.get(provider)
        return first_account(provider) if account is None else account.id

    def account(self, provider: str) -> StoredAccount | None:
        return self._chosen.get(provider)

    def choose(self, account: StoredAccount) -> None:
        self._chosen[account.provider] = account

    async def prepare(self, provider: str) -> RunAccount:
        account = self._chosen.get(provider)
        if account is None:
            return RunAccount(first_account(provider))
        return await run_account(self._profiles, account)

    def source(self, provider: str) -> "EngineAccounts":
        return EngineAccounts(self, provider)


class EngineAccounts:
    """One engine's view, as its chats' runs need it."""

    def __init__(self, active: ActiveAccounts, provider: str) -> None:
        self._active = active
        self._provider = provider

    def active(self) -> str:
        return self._active.id(self._provider)

    async def prepare(self) -> RunAccount:
        return await self._active.prepare(self._provider)
