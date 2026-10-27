"""An ACP engine's account in Settings (B107).

Nest signs none of them in itself. OpenCode and Cursor sign in with their own command in
Terminal, which `login` gives; Gemini's API key is pasted into Nest and kept in the
Keychain (`set_key`). Whether an account is signed in is asked of the engine service.
"""

from collections.abc import Awaitable, Callable

from nestd.engine.acp import AcpAccountStatus, AcpEngineService
from nestd.errors import ConflictError, InvalidInputError
from nestd.providers.base import RunAccount

# A key longer than any provider's is refused without being repeated.
KEY_LIMIT = 512

# Makes the account's folder ready and gives what the engine runs it on.
type AccountRun = Callable[[], Awaitable[RunAccount]]
# Hears each sign in and sign out.
type Announce = Callable[[AcpAccountStatus, str | None], Awaitable[None]]


class NoKeySignInError(ConflictError):
    """The engine does not sign in with an API key, or needs one pasted instead."""


class AcpAccount:
    def __init__(
        self, service: AcpEngineService, account_id: str, run: AccountRun, announce: Announce
    ) -> None:
        self._service = service
        self._account_id = account_id
        self._run = run
        self._announce = announce

    @property
    def signing_in(self) -> bool:
        """Nothing runs while the user signs in: Terminal or the key field does it."""
        return False

    async def status(self) -> AcpAccountStatus:
        return await self._service.account_status(await self._run())

    async def login(self) -> str | None:
        """Start using the account: the engine is installed if it is missing, and the
        command to run in Terminal is given when the engine has one (None otherwise). An
        API key engine is refused: its key is pasted instead (`set_key`).
        """
        engine = self._service.engine
        if engine.sign_in == "api_key":
            msg = f"Paste your {engine.name} API key to sign in."
            raise NoKeySignInError(msg)
        self._service.install.start()
        return await self._service.login_command(await self._run())

    async def cancel(self) -> None:
        return

    async def logout(self) -> AcpAccountStatus:
        """Forget Nest's key; an engine signed in in Terminal keeps its own login, which its
        own command (or removing the account's folder) signs out.
        """
        if self._service.engine.sign_in == "api_key":
            self._service.delete_key(self._account_id)
        status = await self.status()
        await self._announce(status, None)
        return status

    async def set_key(self, key: str) -> AcpAccountStatus:
        engine = self._service.engine
        if engine.sign_in != "api_key":
            msg = f"{engine.name} does not sign in with an API key"
            raise NoKeySignInError(msg)
        cleaned = key.strip()
        if not cleaned or len(cleaned) > KEY_LIMIT or any(c.isspace() for c in cleaned):
            # Never the key itself in the answer.
            msg = "That does not look like an API key."
            raise InvalidInputError(msg)
        self._service.set_key(self._account_id, cleaned)
        self._service.install.start()
        status = await self.status()
        await self._announce(status, None)
        return status

    async def delete_key(self) -> AcpAccountStatus:
        engine = self._service.engine
        if engine.sign_in != "api_key":
            msg = f"{engine.name} does not sign in with an API key"
            raise NoKeySignInError(msg)
        return await self.logout()

    async def stop(self) -> None:
        return
