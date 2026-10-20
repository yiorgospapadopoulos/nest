from datetime import timedelta

import pytest

from nestd.engine.codex import STORE_PREFIX, CodexEngine
from nestd.engine.store import EngineInfoStore
from nestd.providers.base import AccountInfo, EngineDetails, EngineWindow, ModelOption, UsageInfo
from nestd.providers.codex import CodexNotSignedInError
from nestd.providers.codex_engine import CodexDetails, CodexFetchError, CodexLogin
from nestd.storage.db import Database
from tests.fakes import FakeClock

MODELS = [
    ModelOption(value="default", display_name="Default", description="", effort_levels=["low"]),
    ModelOption(value="gpt-5.5", display_name="GPT-5.5", description=""),
]
ACCOUNT = AccountInfo(email="me@example.com", plan="ChatGPT Plus")


class Fetch:
    def __init__(self) -> None:
        self.calls = 0
        self.details = CodexDetails(MODELS, CodexLogin(True, ACCOUNT))
        self.error: Exception | None = None

    async def __call__(self) -> CodexDetails:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.details


WINDOWS = UsageInfo(
    five_hour=None,
    seven_day=None,
    provider="codex",
    windows=[EngineWindow(utilization=0.25, resets_at=None, minutes=43200)],
)


class FetchUsage:
    def __init__(self) -> None:
        self.calls = 0
        self.error: Exception | None = None

    async def __call__(self) -> UsageInfo | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return WINDOWS


def engine(
    db: Database, clock: FakeClock, fetch: Fetch, usage: FetchUsage | None = None
) -> CodexEngine:
    return CodexEngine(
        EngineInfoStore(db, clock, STORE_PREFIX), fetch, clock, usage or FetchUsage()
    )


async def test_the_status_is_asked_once_while_fresh(db: Database, clock: FakeClock) -> None:
    fetch = Fetch()
    codex = engine(db, clock, fetch)

    first = await codex.status()
    clock.advance(timedelta(seconds=30))
    again = await codex.status()
    clock.advance(timedelta(seconds=31))
    later = await codex.status()
    forced = await codex.status(refresh=True)

    assert first.signed_in
    assert first.account == ACCOUNT
    assert first.checked_at == again.checked_at
    assert later.checked_at > first.checked_at
    assert forced.checked_at == later.checked_at
    assert fetch.calls == 3


async def test_models_and_account_are_kept_apart_from_claudes(
    db: Database, clock: FakeClock
) -> None:
    fetch = Fetch()
    codex = engine(db, clock, fetch)
    claude = EngineInfoStore(db, clock)
    await claude.save(EngineDetails(models=[MODELS[1]], account=AccountInfo(plan="Claude Max")))

    listed = await codex.models()

    assert listed.models == MODELS
    assert await codex.account() == ACCOUNT
    assert (await claude.account()) == AccountInfo(plan="Claude Max")
    assert (await claude.models()).models == [MODELS[1]]  # type: ignore[union-attr]
    assert await codex.find(None) == MODELS[0]
    assert await codex.find("gpt-5.5") == MODELS[1]
    assert await codex.find("gpt-9") is None
    assert (await codex.models()).models == MODELS
    assert fetch.calls == 1


async def test_nothing_is_found_before_codex_reported(db: Database, clock: FakeClock) -> None:
    assert await engine(db, clock, Fetch()).find("gpt-5.5") is None


async def test_without_a_login_new_chats_are_refused(db: Database, clock: FakeClock) -> None:
    fetch = Fetch()
    fetch.details = CodexDetails(MODELS, CodexLogin(False, AccountInfo()))
    codex = engine(db, clock, fetch)

    with pytest.raises(CodexNotSignedInError):
        await codex.require_signed_in()

    fetch.details = CodexDetails(MODELS, CodexLogin(True, ACCOUNT))
    await codex.status(refresh=True)
    await codex.require_signed_in()


async def test_a_codex_that_cannot_be_asked_is_unknown_not_signed_out(
    db: Database, clock: FakeClock
) -> None:
    fetch = Fetch()
    fetch.error = CodexFetchError("FileNotFoundError")
    codex = engine(db, clock, fetch)

    status = await codex.status()
    await codex.require_signed_in()

    assert (status.signed_in, status.error) == (None, "FileNotFoundError")
    assert (await codex.models()).models == []
    assert await codex.account() == AccountInfo()


async def test_usage_is_read_only_while_signed_in(db: Database, clock: FakeClock) -> None:
    fetch, usage = Fetch(), FetchUsage()
    codex = engine(db, clock, fetch, usage)

    assert await codex.usage() == WINDOWS

    fetch.details = CodexDetails(MODELS, CodexLogin(False, AccountInfo()))
    await codex.status(refresh=True)
    assert await codex.usage() is None
    fetch.error = CodexFetchError("timed out")
    await codex.status(refresh=True)
    assert await codex.usage() is None
    assert usage.calls == 1


async def test_usage_that_cannot_be_read_is_none_and_logged(
    db: Database, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    usage = FetchUsage()
    usage.error = CodexFetchError("CodexRpcError")
    codex = engine(db, clock, Fetch(), usage)

    assert await codex.usage() is None
    assert "could not ask Codex for its usage: CodexRpcError" in caplog.text
