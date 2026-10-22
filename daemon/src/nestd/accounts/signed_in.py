"""Whether an engine can run chats on the user's subscription now (B106): what its active
account last answered, else whether Nest ever saw it signed in. Asks no engine, so it is
cheap enough for every check.
"""

from nestd.accounts.active import ActiveAccounts
from nestd.accounts.profiles import CLAUDE, CODEX
from nestd.accounts.store import AccountStore
from nestd.engine.sign_ins import SignInStore


class SignedIn:
    def __init__(self, store: AccountStore, active: ActiveAccounts, sign_ins: SignInStore) -> None:
        self._store = store
        self._active = active
        self._sign_ins = sign_ins

    async def claude(self) -> bool:
        return await self._engine(CLAUDE)

    async def any(self) -> bool:
        return await self._engine(CLAUDE) or await self._engine(CODEX)

    async def _engine(self, provider: str) -> bool:
        account = await self._store.get(self._active.id(provider))
        if account.signed_in is not None:
            return account.signed_in
        return await self._sign_ins.seen(provider)
