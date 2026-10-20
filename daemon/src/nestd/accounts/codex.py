"""The Codex account in Settings (B94), through Codex's own ChatGPT sign-in.

Nest never sees a password or a token. A short-lived app-server against the user's Codex
home is asked `account/login/start` for the ChatGPT browser flow; the link it gives is
opened on the Mac, Codex takes the browser's answer on its own local callback, keeps the
login in the Codex home and says `account/login/completed`. That app-server runs until
then, until the user cancels (`account/login/cancel`), or for at most
`LOGIN_TIME_LIMIT`. Sign out is `account/logout` on another short-lived one. Each outcome
is announced as `account.codex` after Codex is asked again, so the provider list has it
too.
"""

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel, JsonValue

from nestd.engine.codex import CodexEngine, CodexStatus
from nestd.errors import ConflictError, NestError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.codex_engine import CodexFetchError, ask_codex, initialize
from nestd.providers.codex_items import text
from nestd.providers.codex_process import CodexLaunch, TransportFactory
from nestd.providers.codex_rpc import CodexClosedError, CodexRpc, CodexRpcError, JsonObject

logger = logging.getLogger(__name__)

# The user signs in in the browser; past this the sign in is cancelled.
LOGIN_TIME_LIMIT = timedelta(minutes=15)
NOT_FINISHED = "Signing in did not finish"
TIMED_OUT = "Signing in timed out"
ENDED = "Codex stopped before signing in finished"
# The user cancelled: announced without an error.
_CANCELLED = "cancelled"


class CodexAccountStatus(BaseModel):
    """`GET /api/accounts/codex`, asked of Codex now."""

    # None when Codex could not be asked; `error` then says why, in a word.
    signed_in: bool | None
    email: str | None
    # Such as "ChatGPT Plus".
    plan: str | None
    checked_at: datetime
    error: str | None = None


class CodexSignIn(BaseModel):
    """`POST /api/accounts/codex/login`: the page the user signs in on, opened on the Mac."""

    auth_url: str


class CodexSignInRunningError(ConflictError):
    pass


class CodexAccountError(NestError):
    """Codex could not start signing in or sign out; only the kind of failure is named."""

    status_code = 502


@dataclass
class _Login:
    rpc: CodexRpc
    login_id: str
    # Why it ended without a login; None when it succeeded.
    outcome: asyncio.Future[str | None]
    task: asyncio.Task[None]


class CodexAccount:
    def __init__(
        self,
        engine: CodexEngine,
        transport: TransportFactory,
        launch: Callable[[], CodexLaunch],
        bus: EventBus,
        time_limit: timedelta = LOGIN_TIME_LIMIT,
    ) -> None:
        """`launch` starts the app-server against the user's Codex home."""
        self._engine = engine
        self._transport = transport
        self._launch = launch
        self._bus = bus
        self._time_limit = time_limit
        self._lock = asyncio.Lock()
        self._login: _Login | None = None

    async def status(self) -> CodexAccountStatus:
        return _status(await self._engine.status(refresh=True))

    async def login(self) -> CodexSignIn:
        """Start the ChatGPT browser sign in; 409 while one runs, 502 when Codex cannot
        start it. The outcome comes as `account.codex`.
        """
        async with self._lock:
            if self._login is not None:
                msg = "a sign in is already in progress"
                raise CodexSignInRunningError(msg)
            outcome: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
            started: list[str] = []

            async def on_notification(method: str, params: JsonObject) -> None:
                login_id = params.get("loginId")
                if method != "account/login/completed":
                    return
                if login_id is not None and login_id not in started:
                    return
                success = params.get("success") is True
                _end(outcome, None if success else text(params.get("error")) or NOT_FINISHED)

            async def refuse(_method: str, _params: JsonObject) -> JsonValue:
                return {}

            async def on_closed(_reason: str) -> None:
                _end(outcome, ENDED)

            try:
                rpc = CodexRpc(
                    await self._transport(self._launch()), on_notification, refuse, on_closed
                )
            except Exception as error:
                msg = f"Codex could not start signing in ({type(error).__name__})"
                raise CodexAccountError(msg) from error
            login_id, auth_url = await _start(rpc)
            started.append(login_id)
            task = asyncio.create_task(self._finish(rpc, login_id, outcome))
            self._login = _Login(rpc, login_id, outcome, task)
            return CodexSignIn(auth_url=auth_url)

    async def cancel(self) -> None:
        """Stop the sign in that runs, if one does; announced without an error."""
        login = self._login
        if login is None:
            return
        with suppress(CodexRpcError, CodexClosedError):
            await login.rpc.request("account/login/cancel", {"loginId": login.login_id})
        _end(login.outcome, _CANCELLED)
        await asyncio.gather(login.task, return_exceptions=True)

    async def logout(self) -> CodexAccountStatus:
        """`account/logout`, then Codex is asked again; 502 when it cannot sign out."""

        async def sign_out(rpc: CodexRpc) -> None:
            await rpc.request("account/logout", {})

        try:
            await ask_codex(self._transport, self._launch(), sign_out)
        except CodexFetchError as error:
            msg = f"Codex could not sign out ({error})"
            raise CodexAccountError(msg) from error
        status = await self.status()
        await self._announce(status, None)
        return status

    async def stop(self) -> None:
        """The daemon stops: a sign in that runs ends without an announcement."""
        login, self._login = self._login, None
        if login is None:
            return
        login.task.cancel()
        await asyncio.gather(login.task, return_exceptions=True)
        await login.rpc.close()

    async def _finish(
        self, rpc: CodexRpc, login_id: str, outcome: asyncio.Future[str | None]
    ) -> None:
        try:
            try:
                async with asyncio.timeout(self._time_limit.total_seconds()):
                    error = await outcome
            except TimeoutError:
                error = TIMED_OUT
                with suppress(CodexRpcError, CodexClosedError):
                    await rpc.request("account/login/cancel", {"loginId": login_id})
            await rpc.close()
            status = await self.status()
            await self._announce(status, None if error == _CANCELLED else error)
        finally:
            if self._login is not None and self._login.outcome is outcome:
                self._login = None

    async def _announce(self, status: CodexAccountStatus, error: str | None) -> None:
        payload: dict[str, JsonValue] = {**status.model_dump(mode="json"), "error": error}
        await self._bus.publish(types.ACCOUNT_CODEX, payload)


def _end(outcome: asyncio.Future[str | None], value: str | None) -> None:
    """The first way the sign in ended counts."""
    if not outcome.done():
        outcome.set_result(value)


async def _start(rpc: CodexRpc) -> tuple[str, str]:
    """The login's id and browser link; the connection is closed when there is none."""
    try:
        await initialize(rpc)
        answer = await rpc.request("account/login/start", {"type": "chatgpt"})
    except (CodexRpcError, CodexClosedError) as error:
        await rpc.close()
        msg = f"Codex could not start signing in ({type(error).__name__})"
        raise CodexAccountError(msg) from error
    login_id, auth_url = text(answer.get("loginId")), text(answer.get("authUrl"))
    if answer.get("type") != "chatgpt" or not login_id or not auth_url:
        await rpc.close()
        msg = "Codex gave no sign-in link"
        raise CodexAccountError(msg)
    return login_id, auth_url


def _status(status: CodexStatus) -> CodexAccountStatus:
    account = status.account
    return CodexAccountStatus(
        signed_in=status.signed_in,
        email=None if account is None else account.email,
        plan=None if account is None else account.plan,
        checked_at=status.checked_at,
        error=status.error,
    )
