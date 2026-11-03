import logging
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.accounts.codex import read_status
from nestd.engine.codex import STORE_PREFIX, CodexEngine
from nestd.engine.store import EngineInfoStore
from nestd.providers.base import AccountInfo, EngineDetails, EngineWindow, ModelOption, UsageInfo
from nestd.providers.codex import CodexNotSignedInError
from nestd.providers.codex_engine import CodexDetails, CodexFetchError, CodexLogin, fetch_codex
from nestd.providers.codex_process import CodexLaunch
from nestd.storage.db import Database
from tests.codex_support import FakeAppServer
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

    # Codex's default entry is kept to learn its default model, never offered (B94).
    assert listed.models == MODELS[1:]
    assert listed.default_model == "gpt-5.5"
    assert await codex.default_model() == "gpt-5.5"
    assert await codex.account() == ACCOUNT
    assert (await claude.account()) == AccountInfo(plan="Claude Max")
    assert (await claude.models()).models == [MODELS[1]]  # type: ignore[union-attr]
    assert await codex.find(None) == MODELS[0]
    assert await codex.find("gpt-5.5") == MODELS[1]
    assert await codex.find("gpt-9") is None
    assert (await codex.models()).models == MODELS[1:]
    assert fetch.calls == 1


async def test_nothing_is_found_before_codex_reported(db: Database, clock: FakeClock) -> None:
    assert await engine(db, clock, Fetch()).find("gpt-5.5") is None
    assert await engine(db, clock, Fetch()).default_model() is None


async def test_a_signed_in_answer_is_recorded(db: Database, clock: FakeClock) -> None:
    fetch = Fetch()
    seen: list[str] = []

    async def signed_in() -> None:
        seen.append("codex")

    codex = CodexEngine(
        EngineInfoStore(db, clock, STORE_PREFIX),
        fetch,
        clock,
        FetchUsage(),
        on_signed_in=signed_in,
    )
    await codex.status()
    fetch.details = CodexDetails(MODELS, CodexLogin(False, AccountInfo()))
    await codex.status(refresh=True)

    assert seen == ["codex"]


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


async def test_a_missing_codex_home_is_not_signed_in_and_starts_no_codex(
    db: Database, clock: FakeClock, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """B117: without ~/.codex (Codex never used, as on a fresh Linux install) Codex reads as
    not signed in, like a Mac without a login: no failure, no warning, and no app-server
    started on every check; once the folder appears, Codex is asked."""
    home = tmp_path / "codex-home"
    server = FakeAppServer()
    launch = CodexLaunch(("codex", "app-server"), {"CODEX_HOME": str(home)})
    codex = CodexEngine(
        EngineInfoStore(db, clock, STORE_PREFIX),
        lambda: fetch_codex(server, launch),
        clock,
        FetchUsage(),
    )

    with caplog.at_level(logging.WARNING):
        first = await codex.status()
        clock.advance(timedelta(minutes=5))
        again = await codex.status(refresh=True)
        account = await read_status(server, launch, clock)

    assert (first.signed_in, first.error) == (False, None)
    assert (again.signed_in, again.error) == (False, None)
    assert (account.signed_in, account.error) == (False, None)
    assert server.launches == []
    assert caplog.text == ""

    home.mkdir()
    assert (await codex.status(refresh=True)).signed_in is True
    assert len(server.launches) == 1
