"""Several subscriptions per engine, one active at a time (B98).

Each account signs in, out and is asked who it is through its engine's own commands, run
on its own folder: the first account on the user's login as without Nest, an added one on
its profile folder (`profiles`). Only the user changes the active account; each turn
starts on it, and runs opened on another one are closed and resume on it.
"""

import asyncio
import logging
import math
import secrets
import uuid
from collections.abc import Awaitable, Callable, Collection, Mapping
from datetime import timedelta
from functools import partial
from pathlib import Path

from pydantic import JsonValue

from nestd.accounts.active import ActiveAccounts, run_account
from nestd.accounts.codex import (
    CodexAccount,
    CodexAccountError,
    CodexAccountStatus,
    account_status,
    read_status,
)
from nestd.accounts.models import (
    Account,
    AccountList,
    AccountSignIn,
    BankedResetUsed,
    ResetOutcome,
)
from nestd.accounts.profiles import CLAUDE, CODEX, Profiles
from nestd.accounts.store import AccountStore, StoredAccount
from nestd.claude_code.account import ClaudeAccount, ClaudeAccountStatus, SignInRunningError
from nestd.claude_code.cli import ClaudeCli, ClaudeCliError
from nestd.clock import Clock
from nestd.engine.codex import CodexEngine
from nestd.errors import ConflictError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import BankedResets, EngineWindow, UsageInfo, UsageWindow
from nestd.providers.codex_engine import CodexFetchError, ask_codex, fetch_codex_usage
from nestd.providers.codex_limits import consume_reset, read_limits
from nestd.providers.codex_process import CodexLaunch, TransportFactory
from nestd.usage.publish import publish_usage
from nestd.usage.refresher import FORCED_SPACING, RefreshTooSoonError, UsageRefresher
from nestd.usage.store import UsageStore

logger = logging.getLogger(__name__)

# Statuses older than this are asked again when the accounts are listed.
STATUS_MAX_AGE = timedelta(seconds=60)
TITLES = {CLAUDE: "Claude", CODEX: "Codex"}
OUTCOMES: dict[str, ResetOutcome] = {
    "reset": "reset",
    "nothingToReset": "nothing_to_reset",
    "noCredit": "no_credit",
    "alreadyRedeemed": "already_redeemed",
}

type Handle = ClaudeAccount | CodexAccount
type Status = ClaudeAccountStatus | CodexAccountStatus
# A Codex app-server launch on the account's folder, from its environment.
type CodexLauncher = Callable[[Mapping[str, str]], CodexLaunch]


class FirstAccountError(ConflictError):
    pass


class NotSignedInError(ConflictError):
    pass


class NoBankedResetsError(ConflictError):
    pass


class Accounts:
    def __init__(
        self,
        *,
        store: AccountStore,
        active: ActiveAccounts,
        profiles: Profiles,
        usage: UsageStore,
        refresher: UsageRefresher,
        bus: EventBus,
        clock: Clock,
        claude_cli: ClaudeCli,
        codex: CodexEngine,
        codex_transport: TransportFactory,
        codex_launch: CodexLauncher,
        close_idle_runs: Callable[[Collection[str]], Awaitable[None]],
        claude_switched: Callable[[], Awaitable[object]],
        new_id: Callable[[], str] = lambda: secrets.token_hex(6),
    ) -> None:
        """`codex` is the engine's view of its active account; `close_idle_runs` closes
        the idle chat runs opened on any of the given accounts, and `claude_switched`
        reads Claude's models and account again once another Claude account is active.
        """
        self._store = store
        self._active = active
        self._profiles = profiles
        self._usage = usage
        self._refresher = refresher
        self._bus = bus
        self._clock = clock
        self._claude_cli = claude_cli
        self._codex = codex
        self._codex_transport = codex_transport
        self._codex_launch = codex_launch
        self._close_idle_runs = close_idle_runs
        self._claude_switched = claude_switched
        self._new_id = new_id
        self._handles: dict[str, Handle] = {}
        # Added and never signed in: removed again when the first sign in does not end
        # signed in.
        self._fresh: set[str] = set()
        # Why the last sign in failed, and why the engine could not be asked, by account.
        self._sign_in_errors: dict[str, str] = {}
        self._status_errors: dict[str, str] = {}
        self._last_refresh: float | None = None
        self._tasks: set[asyncio.Task[object]] = set()
        usage.listen(self._limits_changed)

    def active_id(self, provider: str) -> str:
        return self._active.id(provider)

    async def claude_active(self) -> ClaudeAccount:
        handle = await self._handle(await self._store.get(self._active.id(CLAUDE)))
        assert isinstance(handle, ClaudeAccount)  # noqa: S101 (a Claude account's)
        return handle

    async def codex_active(self) -> CodexAccount:
        handle = await self._handle(await self._store.get(self._active.id(CODEX)))
        assert isinstance(handle, CodexAccount)  # noqa: S101 (a Codex account's)
        return handle

    async def list(self, ask: bool = True) -> AccountList:
        """Every account; with `ask`, the statuses older than STATUS_MAX_AGE are asked
        again, all at once, each with its own folder.
        """
        accounts = await self._store.list()
        if ask:
            now = self._clock.now()
            stale = [
                account
                for account in accounts
                if account.checked_at is None or now - account.checked_at >= STATUS_MAX_AGE
            ]
            if stale:
                await asyncio.gather(*(self._ask(account) for account in stale))
                accounts = await self._store.list()
        return AccountList(accounts=[await self._view(account) for account in accounts])

    async def get(self, account_id: str) -> Account:
        return await self._view(await self._store.get(account_id))

    async def add(self, provider: str) -> AccountSignIn:
        """A new account after the engine's others, signing in at once; 409 while another
        sign in of the engine runs.
        """
        self._require_no_sign_in(provider)
        account_id = self._new_id()
        folder = self._profiles.folder(provider, account_id)
        await asyncio.to_thread(self._profiles.prepare, provider, folder)
        account = await self._store.add(account_id, provider, folder)
        self._fresh.add(account_id)
        try:
            auth_url = await self._start(account)
        except BaseException:
            await self._remove(account, folder)
            raise
        await self._changed()
        return AccountSignIn(account=await self.get(account_id), auth_url=auth_url)

    async def login(self, account_id: str) -> AccountSignIn:
        """Sign in to the account again; 409 while a sign in of its engine runs."""
        account = await self._store.get(account_id)
        self._require_no_sign_in(account.provider)
        await run_account(self._profiles, account)
        self._sign_in_errors.pop(account_id, None)
        auth_url = await self._start(account)
        await self._changed()
        return AccountSignIn(account=await self.get(account_id), auth_url=auth_url)

    async def cancel(self, account_id: str) -> None:
        """Stop the account's sign in, if one runs; announced without an error."""
        handle = await self._handle(await self._store.get(account_id))
        await handle.cancel()

    async def logout(self, account_id: str) -> Account:
        """Sign out of that account only."""
        handle = await self._handle(await self._store.get(account_id))
        await handle.logout()
        return await self.get(account_id)

    async def rename(self, account_id: str, name: str | None) -> Account:
        await self._store.get(account_id)
        await self._store.rename(account_id, name)
        await self._changed()
        return await self.get(account_id)

    async def set_active(self, account_id: str) -> AccountList:
        """Make the account its engine's active one; 409 unless it is signed in."""
        account = await self._store.get(account_id)
        if self._active.id(account.provider) != account_id:
            if account.signed_in is not True:
                msg = "only a signed-in account can be used"
                raise NotSignedInError(msg)
            await self._switch(account)
            await self._changed()
        return await self.list(ask=False)

    async def remove(self, account_id: str) -> AccountList:
        """Sign out of an added account, then delete its folder, windows and row; 409 for
        the first account.
        """
        account = await self._store.get(account_id)
        if account.profile is None:
            msg = "the first account of an engine cannot be removed"
            raise FirstAccountError(msg)
        # Refused before anything is done when the folder is not one of Nest's.
        self._profiles.checked(account.profile)
        if account.signed_in is not False:
            await (await self._handle(account)).logout()
        await self._remove(account, account.profile)
        await self._changed()
        return await self.list(ask=False)

    async def refresh(self) -> AccountList:
        """New windows for every signed-in account: Claude's probed one after another,
        Codex's read; 429 within FORCED_SPACING of the last refresh.
        """
        now = self._clock.now().timestamp()
        spacing = FORCED_SPACING.total_seconds()
        if self._last_refresh is not None and now - self._last_refresh < spacing:
            raise RefreshTooSoonError(math.ceil(spacing - (now - self._last_refresh)))
        self._last_refresh = now
        for account in await self._store.list():
            if account.signed_in is True:
                await self._read_usage(account)
        return await self.list(ask=False)

    async def banked_resets(self, account_id: str) -> BankedResets:
        """A Codex account's banked resets with each credit, read on its own app-server;
        409 for a Claude account, which has none.
        """
        return await self._read_banked(await self._codex_account(account_id))

    async def use_banked_reset(self, account_id: str, credit_id: str) -> BankedResetUsed:
        """Use one of a signed-in Codex account's banked resets, then read its limits again.
        Each request is one attempt, with its own idempotency key.
        """
        account = await self._codex_account(account_id)
        if account.signed_in is not True:
            msg = "only a signed-in Codex account can use a banked reset"
            raise NotSignedInError(msg)
        consume = partial(consume_reset, credit_id=credit_id, idempotency_key=str(uuid.uuid4()))
        try:
            answer = await ask_codex(self._codex_transport, await self._launch_on(account), consume)
        except CodexFetchError as error:
            msg = f"Codex could not use the banked reset ({error})"
            raise CodexAccountError(msg) from error
        outcome = OUTCOMES.get(answer)
        if outcome is None:
            msg = "Codex gave no known outcome for the banked reset"
            raise CodexAccountError(msg)
        try:
            await self._read_banked(account)
        except CodexAccountError as error:
            logger.warning("could not read a Codex account's limits again: %s", error)
        return BankedResetUsed(outcome=outcome, accounts=(await self.list(ask=False)).accounts)

    async def _codex_account(self, account_id: str) -> StoredAccount:
        account = await self._store.get(account_id)
        if account.provider != CODEX:
            msg = "only Codex accounts have banked resets"
            raise NoBankedResetsError(msg)
        return account

    async def _launch_on(self, account: StoredAccount) -> CodexLaunch:
        return self._codex_launch((await run_account(self._profiles, account)).env)

    async def _read_banked(self, account: StoredAccount) -> BankedResets:
        """A detailed read of the account's limits, kept with its banked resets."""
        read = partial(read_limits, details=True)
        try:
            usage, banked = await ask_codex(
                self._codex_transport, await self._launch_on(account), read
            )
        except CodexFetchError as error:
            msg = f"Codex could not say its banked resets ({error})"
            raise CodexAccountError(msg) from error
        banked = banked or BankedResets(available=0, credits=[])
        if usage is None:
            await self._usage.update_banked(account.id, banked)
        else:
            await self._usage.update_limits(usage.model_copy(update={"banked": banked}), account.id)
            if account.id == self._active.id(CODEX):
                await publish_usage(self._bus, usage)
        return banked

    async def read_other_codex(self) -> None:
        """The windows of every signed-in Codex account but the active one, on the usage
        schedule; no model runs.
        """
        for account in await self._store.list():
            if (
                account.provider == CODEX
                and account.signed_in is True
                and account.id != self._active.id(CODEX)
            ):
                await self._read_usage(account)

    async def stop(self) -> None:
        for handle in list(self._handles.values()):
            await handle.stop()
        tasks, self._tasks = self._tasks, set[asyncio.Task[object]]()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _require_no_sign_in(self, provider: str) -> None:
        if any(
            handle.signing_in
            for handle in self._handles.values()
            if isinstance(handle, ClaudeAccount) == (provider == CLAUDE)
        ):
            msg = "a sign in is already in progress"
            raise SignInRunningError(msg)

    async def _start(self, account: StoredAccount) -> str | None:
        handle = await self._handle(account)
        if isinstance(handle, ClaudeAccount):
            await handle.login()
            return None
        return (await handle.login()).auth_url

    async def _handle(self, account: StoredAccount) -> Handle:
        handle = self._handles.get(account.id)
        if handle is None:
            env = self._profiles.env(account.provider, account.profile)
            announce = partial(self._outcome, account.id)
            if account.provider == CLAUDE:
                handle = ClaudeAccount(self._claude_cli, self._clock, announce, env)
            else:
                handle = CodexAccount(
                    partial(self._codex_status, account.id, env),
                    self._codex_transport,
                    partial(self._codex_launch, env),
                    announce,
                )
            self._handles[account.id] = handle
        return handle

    async def _codex_status(self, account_id: str, env: Mapping[str, str]) -> CodexAccountStatus:
        """The active account through the engine, so its view stays current."""
        if account_id == self._active.id(CODEX):
            return account_status(await self._codex.status(refresh=True))
        return await read_status(self._codex_transport, self._codex_launch(env), self._clock)

    async def _ask(self, account: StoredAccount) -> Status | None:
        """The engine's answer about the account, kept; None when Claude Code failed."""
        handle = await self._handle(account)
        try:
            status = await handle.status()
        except ClaudeCliError as error:
            self._status_errors[account.id] = str(error)
            await self._store.record(account.id, None, None, None)
            return None
        await self._record(account.id, status)
        return status

    async def _record(self, account_id: str, status: Status) -> None:
        error = status.error if isinstance(status, CodexAccountStatus) else None
        if error is None:
            self._status_errors.pop(account_id, None)
        else:
            self._status_errors[account_id] = error
        await self._store.record(account_id, status.signed_in, status.email, status.plan)

    async def _outcome(self, account_id: str, status: Status, error: str | None) -> None:
        """A sign in ended, or the account signed out."""
        await self._record(account_id, status)
        if error is None:
            self._sign_in_errors.pop(account_id, None)
        else:
            self._sign_in_errors[account_id] = error
        account = await self._store.get(account_id)
        # An added account's first sign in (it always has a profile).
        fresh = account.profile if account_id in self._fresh else None
        if fresh is not None and status.signed_in is not True:
            await self._remove(account, fresh)
            await self._changed()
            return
        if fresh is not None:
            # Never active yet: its windows are read once now.
            self._fresh.discard(account_id)
            await self._read_usage(account)
        if account_id == self._active.id(account.provider):
            await self._announce(account.provider, status, error)
        await self._changed()

    async def _announce(self, provider: str, status: Status, error: str | None) -> None:
        """The active account's status as before B98, for the clients that read it."""
        payload: dict[str, JsonValue] = {**status.model_dump(mode="json"), "error": error}
        kind = types.ACCOUNT_CLAUDE if provider == CLAUDE else types.ACCOUNT_CODEX
        await self._bus.publish(kind, payload)

    async def _read_usage(self, account: StoredAccount) -> None:
        """New windows for one account: a probe for Claude, a read for Codex."""
        active = account.id == self._active.id(account.provider)
        if account.provider == CLAUDE:
            await self._refresher.probe(await run_account(self._profiles, account), active)
            return
        if active:
            info = await self._codex.usage()
        else:
            info = await self._codex_usage(account)
        if info is not None:
            await self._usage.update_limits(info, account.id)
            if active:
                await publish_usage(self._bus, info)

    async def _codex_usage(self, account: StoredAccount) -> UsageInfo | None:
        try:
            return await fetch_codex_usage(self._codex_transport, await self._launch_on(account))
        except CodexFetchError as error:
            logger.warning("could not ask a Codex account for its usage: %s", error)
            return None

    async def _switch(self, account: StoredAccount) -> None:
        """Turns start on `account` from now; idle runs on the engine's others close."""
        provider = account.provider
        await self._store.set_active(provider, account.id)
        self._active.choose(account)
        others = {a.id for a in await self._store.list() if a.provider == provider} - {account.id}
        await self._close_idle_runs(others)
        if provider == CODEX:
            self._codex.forget()
        else:
            self._background(self._claude_switched())
        self._refresher.wake()
        # The new active account's status and windows, as the engine's.
        status = await self._ask(account)
        if status is not None:
            await self._announce(provider, status, None)
        info = await self._stored_usage(account)
        if info.five_hour or info.seven_day or info.windows:
            await publish_usage(self._bus, info)

    async def _stored_usage(self, account: StoredAccount) -> UsageInfo:
        """The account's last known windows, as its engine reports them."""
        if account.provider == CLAUDE:
            limits = await self._usage.limits(account.id)
            five_hour, seven_day = (
                None if w is None else UsageWindow(utilization=w.utilization, resets_at=w.resets_at)
                for w in (limits.five_hour, limits.seven_day)
            )
            return UsageInfo(five_hour=five_hour, seven_day=seven_day)
        windows = [
            EngineWindow(utilization=w.utilization, resets_at=w.resets_at, minutes=w.minutes)
            for w in (await self._usage.engine_limits(CODEX, account.id)).windows
        ]
        return UsageInfo(five_hour=None, seven_day=None, provider=CODEX, windows=windows)

    async def _remove(self, account: StoredAccount, profile: Path) -> None:
        """Delete an added account: its folder, windows and row. If it was active, the
        engine's first signed-in account takes over, else its first account.
        """
        try:
            handle = self._handles.pop(account.id, None)
            if handle is not None:
                await handle.stop()
            await asyncio.to_thread(self._profiles.remove, profile)
            await self._usage.forget(account.id)
            await self._store.delete(account.id)
        finally:
            self._fresh.discard(account.id)
            self._sign_in_errors.pop(account.id, None)
            self._status_errors.pop(account.id, None)
        await self._close_idle_runs({account.id})
        if self._active.id(account.provider) == account.id:
            remaining = [a for a in await self._store.list() if a.provider == account.provider]
            signed_in = [a for a in remaining if a.signed_in is True]
            await self._switch((signed_in or remaining)[0])

    async def _view(self, account: StoredAccount) -> Account:
        handle = self._handles.get(account.id)
        return Account(
            id=account.id,
            provider=account.provider,
            name=account.name,
            title=account.name or account.email or TITLES[account.provider],
            email=account.email,
            plan=account.plan,
            signed_in=account.signed_in,
            active=self._active.id(account.provider) == account.id,
            first=account.first,
            signing_in=handle is not None and handle.signing_in,
            error=self._sign_in_errors.get(account.id) or self._status_errors.get(account.id),
            limits=await self._usage.windows(account.id),
            checked_at=account.checked_at,
            banked_resets=None
            if account.provider == CLAUDE
            else await self._usage.banked(account.id),
        )

    async def _limits_changed(self, _account_id: str) -> None:
        await self._changed()

    async def _changed(self) -> None:
        payload = (await self.list(ask=False)).model_dump(mode="json")
        await self._bus.publish(types.ACCOUNTS_CHANGED, payload)

    def _background(self, work: Awaitable[object]) -> None:
        async def run() -> object:
            return await work

        task = asyncio.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
