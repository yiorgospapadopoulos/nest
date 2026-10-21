"""B94: the Codex account in Settings, through Codex's own ChatGPT sign-in.

The app-server is the in-memory fake: `account/login/start` gives the browser link, and
the test sends `account/login/completed` as Codex would once the user signed in.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from nestd.accounts.codex import CodexAccount, CodexAccountStatus, account_status
from nestd.engine.codex import STORE_PREFIX, CodexEngine
from nestd.engine.store import EngineInfoStore
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.codex_engine import fetch_codex, fetch_codex_usage
from nestd.providers.codex_process import CodexLaunch
from nestd.providers.codex_rpc import JsonObject
from nestd.storage.db import Database
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.codex_support import SIGNED_IN, SIGNED_OUT, FakeAppServer, FakeTransport
from tests.fakes import FakeClock, FakeSecretStore

AUTH_URL = "https://auth.openai.com/oauth/authorize?client_id=codex&state=abc"
STARTED: JsonObject = {"type": "chatgpt", "loginId": "login-1", "authUrl": AUTH_URL}


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        running.codex.answers["account/login/start"] = STARTED
        running.codex.answers["account/login/cancel"] = {"status": "canceled"}
        running.codex.answers["account/logout"] = {}
        yield running


async def published(api: Api) -> list[dict[str, Any]]:
    return await stored(api.ctx.db)


async def stored(db: Database) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        "SELECT payload FROM events WHERE type = ? ORDER BY id", (types.ACCOUNT_CODEX,)
    )
    return [json.loads(row["payload"]) for row in rows]


async def announced(api: Api, count: int = 1) -> list[dict[str, Any]]:
    async def arrived() -> bool:
        return len(await published(api)) >= count

    await until(arrived)
    return await published(api)


def completed(transport: FakeTransport, success: bool, error: str | None = None) -> None:
    transport.push(
        {
            "method": "account/login/completed",
            "params": {
                "loginId": "login-1",
                "success": success,
                "error": error,
                "onboardingEntrypoint": None,
            },
        }
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/accounts/codex"),
        ("POST", "/api/accounts/codex/login"),
        ("POST", "/api/accounts/codex/login/cancel"),
        ("POST", "/api/accounts/codex/logout"),
    ],
)
async def test_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_the_status_asks_codex_now(api: Api) -> None:
    signed_in = (await api.http.get("/api/accounts/codex")).json()
    api.codex.answers["account/read"] = SIGNED_OUT
    signed_out = (await api.http.get("/api/accounts/codex")).json()

    assert signed_in["signed_in"] is True
    assert (signed_in["email"], signed_in["plan"], signed_in["error"]) == (
        "me@example.com",
        "ChatGPT Plus",
        None,
    )
    assert (signed_out["signed_in"], signed_out["email"], signed_out["plan"]) == (
        False,
        None,
        None,
    )
    assert len(api.codex.requests("account/read")) == 2


async def test_a_codex_that_cannot_be_asked_says_why(api: Api) -> None:
    api.codex.spawn_error = OSError("no binary")

    status = (await api.http.get("/api/accounts/codex")).json()

    assert (status["signed_in"], status["error"]) == (None, "OSError")


async def test_signing_in_opens_codexs_own_link_and_announces_the_login(api: Api) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT

    started = await api.http.post("/api/accounts/codex/login")
    login = api.codex.transport
    again = await api.http.post("/api/accounts/codex/login")
    api.codex.answers["account/read"] = SIGNED_IN
    completed(login, success=True)
    [event] = await announced(api)
    providers = (await api.http.get("/api/providers")).json()["providers"]

    assert started.status_code == 200
    assert started.json() == {"auth_url": AUTH_URL}
    assert again.status_code == 409
    # The ChatGPT browser flow on the user's real Codex home, through the app-server only.
    assert api.codex.requests("account/login/start") == [{"type": "chatgpt"}]
    assert login.launch.args[1:] == ("app-server", "--listen", "stdio://")
    assert login.closed
    assert (event["signed_in"], event["email"], event["plan"], event["error"]) == (
        True,
        "me@example.com",
        "ChatGPT Plus",
        None,
    )
    # The provider list has the new login at once, and Codex counts as signed in.
    assert providers[1]["signed_in"] is True
    assert await api.ctx.sign_ins.first() == "codex"


async def test_a_failed_sign_in_is_announced_with_codexs_reason(api: Api) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT
    await api.http.post("/api/accounts/codex/login")

    completed(api.codex.transport, success=False, error="Access denied")
    [event] = await announced(api)

    assert (event["signed_in"], event["error"]) == (False, "Access denied")


async def test_a_failure_without_a_reason_says_it_failed(api: Api) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT
    await api.http.post("/api/accounts/codex/login")

    completed(api.codex.transport, success=False)
    [event] = await announced(api)

    assert event["error"] == "Signing in did not finish"


async def test_another_logins_completion_is_not_this_one(api: Api) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT
    await api.http.post("/api/accounts/codex/login")
    login = api.codex.transport

    login.push(
        {
            "method": "account/login/completed",
            "params": {"loginId": "other", "success": True, "error": None},
        }
    )
    login.push({"method": "account/updated", "params": {"authMode": None, "planType": None}})
    await asyncio.sleep(0.05)
    assert await published(api) == []
    completed(login, success=True)

    assert len(await announced(api)) == 1


async def test_cancelling_stops_codexs_sign_in_quietly(api: Api) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT
    await api.http.post("/api/accounts/codex/login")
    login = api.codex.transport

    cancelled = await api.http.post("/api/accounts/codex/login/cancel")
    [event] = await published(api)
    nothing = await api.http.post("/api/accounts/codex/login/cancel")

    assert cancelled.status_code == 204
    assert api.codex.requests("account/login/cancel") == [{"loginId": "login-1"}]
    assert login.closed
    # A cancel is no failure to show.
    assert (event["signed_in"], event["error"]) == (False, None)
    assert nothing.status_code == 204
    assert len(await published(api)) == 1
    # A new sign in can start.
    assert (await api.http.post("/api/accounts/codex/login")).status_code == 200


async def test_a_cancel_after_codex_said_how_it_ended_keeps_that(api: Api) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT
    await api.http.post("/api/accounts/codex/login")
    login = api.codex.transport

    def cancelled(_params: JsonObject) -> JsonObject:
        completed(login, success=False, error="Access denied")
        return {"status": "canceled"}

    api.codex.answers["account/login/cancel"] = cancelled
    await asyncio.sleep(0)

    await api.http.post("/api/accounts/codex/login/cancel")
    [event] = await announced(api)

    assert event["error"] == "Access denied"


async def test_codex_asking_anything_while_signing_in_gets_an_empty_answer(api: Api) -> None:
    await api.http.post("/api/accounts/codex/login")

    answer = await api.codex.request("item/tool/requestUserInput", {"questions": []})

    assert answer["result"] == {}


async def test_codex_ending_before_the_sign_in_finished_is_a_failure(api: Api) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT
    await api.http.post("/api/accounts/codex/login")

    api.codex.transport.end()
    [event] = await announced(api)

    assert event["error"] == "Codex stopped before signing in finished"


@pytest.mark.parametrize(
    ("setup", "detail"),
    [
        ("spawn", "Codex could not start signing in (OSError)"),
        ("error", "Codex could not start signing in (CodexRpcError)"),
        ("answer", "Codex gave no sign-in link"),
    ],
)
async def test_a_sign_in_codex_cannot_start_is_a_bad_gateway(
    api: Api, setup: str, detail: str
) -> None:
    if setup == "spawn":
        api.codex.spawn_error = OSError("no binary")
    elif setup == "error":
        api.codex.errors["account/login/start"] = (-32600, "port 1455 in use")
    else:
        api.codex.answers["account/login/start"] = {"type": "apiKey"}

    response = await api.http.post("/api/accounts/codex/login")

    assert response.status_code == 502
    assert response.json() == {"detail": detail}
    if setup != "spawn":
        assert api.codex.transport.closed
    api.codex.spawn_error = None
    api.codex.errors.clear()
    api.codex.answers["account/login/start"] = STARTED
    assert (await api.http.post("/api/accounts/codex/login")).status_code == 200


async def test_signing_out_asks_codex_and_announces_it(api: Api) -> None:
    def logged_out(_params: JsonObject) -> JsonObject:
        api.codex.answers["account/read"] = SIGNED_OUT
        return {}

    api.codex.answers["account/logout"] = logged_out

    response = await api.http.post("/api/accounts/codex/logout")
    [event] = await published(api)

    assert response.status_code == 200
    assert response.json()["signed_in"] is False
    assert len(api.codex.requests("account/logout")) == 1
    assert (event["signed_in"], event["error"]) == (False, None)


async def test_a_sign_out_codex_cannot_do_is_a_bad_gateway(api: Api) -> None:
    api.codex.errors["account/logout"] = (-32603, "keyring locked")

    response = await api.http.post("/api/accounts/codex/logout")

    assert response.status_code == 502
    assert response.json() == {"detail": "Codex could not sign out (CodexRpcError)"}
    assert await published(api) == []


async def test_a_sign_in_that_takes_too_long_is_cancelled(db: Database, clock: FakeClock) -> None:
    server = FakeAppServer()
    server.answers["account/login/start"] = STARTED
    server.answers["account/read"] = SIGNED_OUT

    def launch() -> CodexLaunch:
        return CodexLaunch(("codex", "app-server", "--listen", "stdio://"), {})

    engine = CodexEngine(
        EngineInfoStore(db, clock, STORE_PREFIX),
        lambda: fetch_codex(server, launch()),
        clock,
        lambda: fetch_codex_usage(server, launch()),
    )
    bus = EventBus(db, clock)

    async def status() -> CodexAccountStatus:
        return account_status(await engine.status(refresh=True))

    async def announce(status: CodexAccountStatus, error: str | None) -> None:
        await bus.publish(types.ACCOUNT_CODEX, {**status.model_dump(mode="json"), "error": error})

    account = CodexAccount(status, server, launch, announce, time_limit=timedelta(milliseconds=20))

    await account.login()
    login = server.transport

    async def done() -> bool:
        return len(await stored(db)) == 1

    await until(done)
    [event] = await stored(db)
    assert event["error"] == "Signing in timed out"
    assert server.requests("account/login/cancel") == [{"loginId": "login-1"}]
    assert login.closed
    await account.stop()


async def test_stopping_the_daemon_ends_a_sign_in(db: Database, clock: FakeClock) -> None:
    server = FakeAppServer()
    server.answers["account/login/start"] = STARTED

    def launch() -> CodexLaunch:
        return CodexLaunch(("codex",), {})

    engine = CodexEngine(
        EngineInfoStore(db, clock, STORE_PREFIX),
        lambda: fetch_codex(server, launch()),
        clock,
        lambda: fetch_codex_usage(server, launch()),
    )

    async def status() -> CodexAccountStatus:
        return account_status(await engine.status(refresh=True))

    async def announce(_status: CodexAccountStatus, _error: str | None) -> None:
        raise AssertionError

    account = CodexAccount(status, server, launch, announce)

    await account.login()
    await account.stop()
    await account.stop()

    assert server.transport.closed
