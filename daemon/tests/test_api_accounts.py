"""B98: several subscriptions per engine, one active at a time.

The first account of each engine is the user's own login; an added one lives in a profile
folder under the data folder. Every `claude` command here is the fake one and every Codex
app-server the in-memory one; the "first account" folders are stand-ins in `tmp_path`.
"""

import asyncio
import copy
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from nestd.accounts.active import ActiveAccounts
from nestd.accounts.codex import CodexSignInRunningError
from nestd.accounts.profiles import FirstAccount, Profiles
from nestd.accounts.store import AccountStore
from nestd.artifacts.models import Origin
from nestd.claude_code.account import SignInRunningError
from nestd.events import types
from nestd.gitops.runner import CommandError
from nestd.providers.codex_items import obj
from nestd.providers.codex_rpc import JsonObject
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.codex_support import RATE_LIMITS, SIGNED_IN, SIGNED_OUT, FakeTransport
from tests.fake_probe import answer
from tests.fakes import FakeClock, FakeSecretStore

STATUS = ("auth", "status", "--json")
LOGIN = ("auth", "login", "--claudeai")
LOGOUT = ("auth", "logout")
AUTH_URL = "https://auth.openai.com/oauth/authorize?client_id=codex&state=abc"
STARTED: JsonObject = {"type": "chatgpt", "loginId": "login-1", "authUrl": AUTH_URL}
WORK_CODEX: JsonObject = {
    "account": {"type": "chatgpt", "email": "work@example.com", "planType": "pro"},
    "requiresOpenaiAuth": True,
}


def claude_status(email: str | None, plan: str = "max") -> str:
    if email is None:
        return json.dumps({"loggedIn": False})
    return json.dumps({"loggedIn": True, "email": email, "subscriptionType": plan})


@pytest.fixture
def first(tmp_path: Path) -> Path:
    """The stand-in for the user's own folders: Claude's, its account file, Codex's."""
    claude = tmp_path / "claude"
    (claude / "skills").mkdir(parents=True)
    (claude / "CLAUDE.md").write_text("mine", encoding="utf-8")
    (claude / ".credentials.json").write_text("secret", encoding="utf-8")
    (tmp_path / "claude.json").write_text(
        json.dumps({"oauthAccount": {}, "mcpServers": {"fs": {"command": "fs"}}}), "utf-8"
    )
    codex = tmp_path / "codex"
    (codex / "sessions").mkdir(parents=True)
    (codex / "config.toml").write_text("model = 'x'\n", encoding="utf-8")
    (codex / "auth.json").write_text("{}", encoding="utf-8")
    return tmp_path


@pytest.fixture
async def api(first: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(first, clock, secrets, codex_home=first / "codex") as running:
        running.claude.script(*STATUS, reply=claude_status("me@example.com"))
        running.claude.script(*LOGOUT, reply="Successfully logged out.\n")
        running.codex.answers["account/login/start"] = STARTED
        running.codex.answers["account/login/cancel"] = {"status": "canceled"}
        running.codex.answers["account/logout"] = {}
        yield running


async def accounts(api: Api) -> list[dict[str, Any]]:
    response = await api.http.get("/api/accounts")
    assert response.status_code == 200
    return response.json()["accounts"]


async def published(api: Api, kind: str) -> list[dict[str, Any]]:
    rows = await api.ctx.db.fetch_all(
        "SELECT payload FROM events WHERE type = ? ORDER BY id", (kind,)
    )
    return [json.loads(row["payload"]) for row in rows]


def profile_of(api: Api, provider: str, account_id: str) -> Path:
    return api.ctx.paths.data_dir / "profiles" / provider / account_id


async def add_claude(api: Api, email: str = "work@example.com") -> dict[str, Any]:
    """An added Claude account, signed in; its probe after the sign in finds no reply."""
    gate = asyncio.Event()
    api.claude.gates[LOGIN] = gate
    response = await api.http.post("/api/accounts/claude")
    assert response.status_code == 202
    added = response.json()["account"]
    profile = profile_of(api, "claude", added["id"])
    api.claude.script(*LOGIN, reply="Login successful.\n", profile=profile)
    api.claude.script(*STATUS, reply=claude_status(email), profile=profile)
    api.claude.script(*LOGOUT, reply="Successfully logged out.\n", profile=profile)
    gate.set()
    del api.claude.gates[LOGIN]

    async def signed_in() -> bool:
        return any(a["id"] == added["id"] and a["signed_in"] for a in await accounts(api))

    await until(signed_in)
    return added


async def add_codex(api: Api) -> dict[str, Any]:
    response = await api.http.post("/api/accounts/codex")
    assert response.status_code == 202
    added = response.json()["account"]
    profile = str(profile_of(api, "codex", added["id"]))
    api.codex.home_answers[profile] = {"account/read": WORK_CODEX}
    completed(api.codex.transport, success=True)

    async def signed_in() -> bool:
        return any(a["id"] == added["id"] and a["signed_in"] for a in await accounts(api))

    await until(signed_in)
    return added


def completed(transport: FakeTransport, success: bool) -> None:
    transport.push(
        {
            "method": "account/login/completed",
            "params": {"loginId": "login-1", "success": success, "error": None},
        }
    )


def first_dir(api: Api) -> Path:
    claude_dir = api.ctx.paths.claude_dir
    assert claude_dir is not None
    return claude_dir


def by_id(listed: list[dict[str, Any]], account_id: str) -> dict[str, Any]:
    return next(account for account in listed if account["id"] == account_id)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/accounts"),
        ("POST", "/api/accounts/refresh"),
        ("POST", "/api/accounts/claude"),
        ("POST", "/api/accounts/claude-main/login"),
        ("POST", "/api/accounts/claude-main/login/cancel"),
        ("POST", "/api/accounts/claude-main/logout"),
        ("PUT", "/api/accounts/claude-main/name"),
        ("PUT", "/api/accounts/claude-main/active"),
        ("DELETE", "/api/accounts/claude-main"),
    ],
)
async def test_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_the_first_accounts_are_listed_claudes_first_and_asked_once_a_minute(
    api: Api, clock: FakeClock
) -> None:
    listed = await accounts(api)
    again = await accounts(api)
    clock.advance(timedelta(seconds=61))
    await accounts(api)

    assert [(a["id"], a["provider"], a["first"], a["active"]) for a in listed] == [
        ("claude-main", "claude", True, True),
        ("codex-main", "codex", True, True),
    ]
    claude, codex = listed
    assert claude["checked_at"] is not None
    assert {key: value for key, value in claude.items() if key != "checked_at"} == {
        "id": "claude-main",
        "provider": "claude",
        "name": None,
        "title": "me@example.com",
        "email": "me@example.com",
        "plan": "Claude Max",
        "signed_in": True,
        "active": True,
        "first": True,
        "signing_in": False,
        "error": None,
        "limits": [],
        "banked_resets": None,
    }
    assert (codex["title"], codex["plan"], codex["signed_in"]) == (
        "me@example.com",
        "ChatGPT Plus",
        True,
    )
    assert again == listed
    # The first account runs as without Nest: no CLAUDE_CONFIG_DIR is set.
    assert api.claude.runs() == [({}, STATUS), ({}, STATUS)]
    assert len(api.codex.requests("account/read")) == 2


async def test_an_engine_that_cannot_be_asked_says_why_and_keeps_who_it_was(
    api: Api, clock: FakeClock
) -> None:
    await accounts(api)
    api.claude.replies.clear()
    api.claude.script(*STATUS, reply=CommandError(["claude"], 1, "broken\n"))
    api.codex.spawn_error = OSError("no binary")
    clock.advance(timedelta(minutes=2))

    claude, codex = await accounts(api)

    assert (claude["signed_in"], claude["email"], claude["error"]) == (
        None,
        "me@example.com",
        "broken",
    )
    assert (codex["signed_in"], codex["error"]) == (None, "OSError")


async def test_an_added_claude_account_signs_in_on_its_own_profile(api: Api) -> None:
    api.probes.replies.append(answer(0.3, 0.1))

    added = await add_claude(api)

    profile = profile_of(api, "claude", added["id"])
    assert len(added["id"]) == 12
    assert (added["signing_in"], added["active"], added["first"]) == (True, False, False)
    claude_dir = api.ctx.paths.claude_dir
    assert claude_dir is not None
    assert (profile / "CLAUDE.md").readlink() == claude_dir / "CLAUDE.md"
    assert not (profile / ".credentials.json").exists()
    assert json.loads((profile / ".claude.json").read_text(encoding="utf-8")) == {
        "mcpServers": {"fs": {"command": "fs"}}
    }
    env = {"CLAUDE_CONFIG_DIR": str(profile)}
    assert (env, LOGIN) in api.claude.runs()
    assert all(args != LOGIN or run_env == env for run_env, args in api.claude.runs())
    listed = by_id(await accounts(api), added["id"])
    assert (listed["title"], listed["active"], listed["signing_in"]) == (
        "work@example.com",
        False,
        False,
    )
    # Probed once after its sign in, on its profile, without announcing it as Claude's.
    [probe] = api.probes.clients
    assert probe.options.env == env
    assert [w["label"] for w in listed["limits"]] == ["5 hour", "Weekly"]
    assert await published(api, types.USAGE_UPDATED) == []
    assert await published(api, types.ACCOUNT_CLAUDE) == []
    changed = await published(api, types.ACCOUNTS_CHANGED)
    assert [a["id"] for a in changed[-1]["accounts"]] == ["claude-main", added["id"], "codex-main"]


async def test_only_one_sign_in_of_an_engine_runs_at_a_time(api: Api) -> None:
    gate = asyncio.Event()
    api.claude.gates[LOGIN] = gate

    first = await api.http.post("/api/accounts/claude")
    second = await api.http.post("/api/accounts/claude")
    again = await api.http.post("/api/accounts/claude-main/login")
    codex = await api.http.post("/api/accounts/codex")

    assert first.status_code == 202
    assert (second.status_code, again.status_code, codex.status_code) == (409, 409, 202)
    assert len(await accounts(api)) == 4
    gate.set()


async def test_a_new_account_whose_first_sign_in_fails_is_removed(api: Api) -> None:
    gate = asyncio.Event()
    api.claude.gates[LOGIN] = gate
    added = (await api.http.post("/api/accounts/claude")).json()["account"]
    profile = profile_of(api, "claude", added["id"])
    api.claude.script(*LOGIN, reply=CommandError(["claude"], 1, "Login failed\n"), profile=profile)
    api.claude.script(*STATUS, reply=claude_status(None), profile=profile)
    gate.set()

    async def gone() -> bool:
        return len(await accounts(api)) == 2

    await until(gone)
    assert not profile.exists()
    assert (first_dir(api) / "CLAUDE.md").read_text(encoding="utf-8") == "mine"
    assert await published(api, types.ACCOUNT_CLAUDE) == []


async def test_cancelling_a_new_accounts_sign_in_removes_it(api: Api) -> None:
    api.claude.gates[LOGIN] = asyncio.Event()
    added = (await api.http.post("/api/accounts/claude")).json()["account"]

    response = await api.http.post(f"/api/accounts/{added['id']}/login/cancel")

    assert response.status_code == 204
    assert [a["id"] for a in await accounts(api)] == ["claude-main", "codex-main"]
    assert not profile_of(api, "claude", added["id"]).exists()


async def test_cancelling_when_no_sign_in_runs_does_nothing(api: Api) -> None:
    response = await api.http.post("/api/accounts/claude-main/login/cancel")

    assert response.status_code == 204
    assert await published(api, types.ACCOUNT_CLAUDE) == []


async def test_an_added_codex_account_signs_in_on_its_own_home_and_shares_the_state(
    api: Api, first: Path
) -> None:
    response = await api.http.post("/api/accounts/codex")
    body = response.json()
    profile = profile_of(api, "codex", body["account"]["id"])
    api.codex.home_answers[str(profile)] = {"account/read": WORK_CODEX}
    login = api.codex.launches[-1]
    completed(api.codex.transport, success=True)

    async def signed_in() -> bool:
        return by_id(await accounts(api), body["account"]["id"])["signed_in"] is True

    await until(signed_in)

    assert body["auth_url"] == AUTH_URL
    assert login.env["CODEX_HOME"] == str(profile)
    assert login.env["CODEX_SQLITE_HOME"] == str(first / "codex")
    assert sorted(entry.name for entry in profile.iterdir()) == ["config.toml", "sessions"]
    listed = by_id(await accounts(api), body["account"]["id"])
    assert (listed["title"], listed["plan"]) == ("work@example.com", "ChatGPT Pro")
    # Its windows were read once, on its own home, without a model call.
    assert api.codex.homes().count(str(profile)) >= 3
    assert [w["label"] for w in listed["limits"]] == ["5 hour", "Weekly"]
    assert await published(api, types.USAGE_PROVIDER_UPDATED) == []
    assert await published(api, types.ACCOUNT_CODEX) == []


async def test_a_new_codex_account_whose_sign_in_fails_is_removed(api: Api) -> None:
    added = (await api.http.post("/api/accounts/codex")).json()["account"]
    profile = profile_of(api, "codex", added["id"])
    api.codex.home_answers[str(profile)] = {"account/read": SIGNED_OUT}
    completed(api.codex.transport, success=False)

    async def gone() -> bool:
        return len(await accounts(api)) == 2

    await until(gone)
    assert not profile.exists()


async def test_a_codex_sign_in_that_cannot_start_leaves_no_account(api: Api) -> None:
    api.codex.errors["account/login/start"] = (-32600, "nope")

    response = await api.http.post("/api/accounts/codex")

    assert response.status_code == 502
    assert len(await accounts(api)) == 2
    assert list((api.ctx.paths.data_dir / "profiles" / "codex").iterdir()) == []


async def test_an_unknown_engine_or_account_is_refused(api: Api) -> None:
    assert (await api.http.post("/api/accounts/gemini")).status_code == 422
    assert (await api.http.put("/api/accounts/nobody/active")).status_code == 404
    assert (await api.http.post("/api/accounts/nobody/logout")).status_code == 404


async def test_an_account_is_renamed_trimmed_and_cleared(api: Api) -> None:
    named = await api.http.put("/api/accounts/claude-main/name", json={"name": "  Personal "})
    long = await api.http.put("/api/accounts/claude-main/name", json={"name": "x" * 41})
    cleared = await api.http.put("/api/accounts/claude-main/name", json={"name": "  "})

    assert (named.json()["name"], named.json()["title"]) == ("Personal", "Personal")
    assert long.status_code == 422
    assert (cleared.json()["name"], cleared.json()["title"]) == (None, "Claude")
    changed = await published(api, types.ACCOUNTS_CHANGED)
    assert by_id(changed[0]["accounts"], "claude-main")["name"] == "Personal"


async def test_only_a_signed_in_account_becomes_active(api: Api) -> None:
    gate = asyncio.Event()
    api.claude.gates[LOGIN] = gate
    added = (await api.http.post("/api/accounts/claude")).json()["account"]

    response = await api.http.put(f"/api/accounts/{added['id']}/active")
    same = await api.http.put("/api/accounts/claude-main/active")

    assert response.status_code == 409
    assert same.status_code == 200
    assert [a["active"] for a in same.json()["accounts"]] == [True, False, True]
    gate.set()


async def test_switching_runs_the_next_turns_and_the_old_routes_on_the_new_account(
    api: Api,
) -> None:
    await accounts(api)
    added = await add_claude(api)
    profile = profile_of(api, "claude", added["id"])
    env = {"CLAUDE_CONFIG_DIR": str(profile)}
    before = len(api.claude.runs())

    # The engine's read on the new account is still running when the daemon stops.
    api.engine.hang = True
    response = await api.http.put(f"/api/accounts/{added['id']}/active")
    status = await api.http.get("/api/accounts/claude")
    providers = await api.http.get("/api/providers")

    assert response.status_code == 200
    assert [(a["id"], a["active"]) for a in response.json()["accounts"]][:2] == [
        ("claude-main", False),
        (added["id"], True),
    ]
    assert status.json()["email"] == "work@example.com"
    assert providers.status_code == 200
    assert api.claude.runs()[before:] == [(env, STATUS), (env, STATUS)]
    [event] = await published(api, types.ACCOUNT_CLAUDE)
    assert event["email"] == "work@example.com"
    assert api.ctx.accounts.active_id("claude") == added["id"]
    prepared = await api.ctx.sessions.engines.default.prepare_account()
    assert prepared is not None
    assert prepared.env == env
    # The model list and account are read again on it.
    await until(lambda: len(api.engine.clients) >= 1)
    assert api.engine.clients[-1].options.env == env


async def test_switching_announces_the_new_accounts_known_windows(api: Api) -> None:
    api.probes.replies.append(answer(0.3, 0.1))
    added = await add_claude(api)

    await api.http.put(f"/api/accounts/{added['id']}/active")
    limits = (await api.http.get("/api/usage/limits")).json()

    [usage] = await published(api, types.USAGE_UPDATED)
    assert usage["five_hour"]["utilization"] == 0.3
    assert limits["five_hour"]["utilization"] == 0.3


async def test_switching_codex_asks_codex_again_on_the_new_home(api: Api) -> None:
    added = await add_codex(api)
    profile = str(profile_of(api, "codex", added["id"]))

    await api.http.put(f"/api/accounts/{added['id']}/active")
    status = (await api.http.get("/api/accounts/codex")).json()
    models = await api.http.get("/api/providers")

    assert status["email"] == "work@example.com"
    assert models.status_code == 200
    assert api.codex.homes()[-1] == profile
    [usage] = await published(api, types.USAGE_PROVIDER_UPDATED)
    assert [w["minutes"] for w in usage["windows"]] == [300, 10080]
    [event] = await published(api, types.ACCOUNT_CODEX)
    assert event["email"] == "work@example.com"


async def test_signing_out_of_an_added_account_runs_with_its_profile_only(api: Api) -> None:
    added = await add_claude(api)
    profile = profile_of(api, "claude", added["id"])
    api.claude.replies[str(profile), STATUS] = [claude_status(None)]

    response = await api.http.post(f"/api/accounts/{added['id']}/logout")

    assert response.status_code == 200
    assert (response.json()["signed_in"], response.json()["title"]) == (
        False,
        "work@example.com",
    )
    logouts = [env for env, args in api.claude.runs() if args == LOGOUT]
    assert logouts == [{"CLAUDE_CONFIG_DIR": str(profile)}]
    assert by_id(await accounts(api), "claude-main")["signed_in"] is True


async def test_signing_out_of_the_first_account_runs_as_without_nest(api: Api) -> None:
    response = await api.http.post("/api/accounts/claude-main/logout")

    assert response.status_code == 200
    assert [env for env, args in api.claude.runs() if args == LOGOUT] == [{}]
    [event] = await published(api, types.ACCOUNT_CLAUDE)
    assert event["error"] is None


async def test_the_first_account_cannot_be_removed(api: Api) -> None:
    for account_id in ("claude-main", "codex-main"):
        response = await api.http.delete(f"/api/accounts/{account_id}")
        assert response.status_code == 409
    assert [args for _, args in api.claude.runs() if args == LOGOUT] == []


async def test_removing_an_added_account_signs_it_out_and_deletes_only_its_folder(
    api: Api,
) -> None:
    api.probes.replies.append(answer(0.3, 0.1))
    added = await add_claude(api)
    profile = profile_of(api, "claude", added["id"])
    claude_dir = api.ctx.paths.claude_dir
    assert claude_dir is not None
    before = sorted(path.name for path in claude_dir.rglob("*"))
    await api.http.put(f"/api/accounts/{added['id']}/active")

    response = await api.http.delete(f"/api/accounts/{added['id']}")

    assert response.status_code == 200
    assert [(a["id"], a["active"]) for a in response.json()["accounts"]] == [
        ("claude-main", True),
        ("codex-main", True),
    ]
    assert [env for env, args in api.claude.runs() if args == LOGOUT] == [
        {"CLAUDE_CONFIG_DIR": str(profile)}
    ]
    assert not profile.exists()
    assert sorted(path.name for path in claude_dir.rglob("*")) == before
    assert (claude_dir / ".credentials.json").read_text(encoding="utf-8") == "secret"
    rows = await api.ctx.db.fetch_all(
        "SELECT * FROM usage_limits WHERE account_id = ?", (added["id"],)
    )
    assert rows == []
    assert api.ctx.accounts.active_id("claude") == "claude-main"


async def test_removing_the_active_account_hands_over_to_a_signed_in_one(api: Api) -> None:
    first = await add_codex(api)
    await api.http.put(f"/api/accounts/{first['id']}/active")
    api.codex.answers["account/read"] = SIGNED_OUT
    await api.http.post("/api/accounts/codex-main/logout")
    api.codex.answers["account/read"] = SIGNED_IN
    second = await add_codex(api)

    response = await api.http.delete(f"/api/accounts/{first['id']}")

    assert [(a["id"], a["active"]) for a in response.json()["accounts"]][1:] == [
        ("codex-main", False),
        (second["id"], True),
    ]


async def test_a_signed_out_account_is_removed_without_signing_out(api: Api) -> None:
    added = await add_claude(api)
    profile = profile_of(api, "claude", added["id"])
    api.claude.replies[str(profile), STATUS] = [claude_status(None)]
    await api.http.post(f"/api/accounts/{added['id']}/logout")

    await api.http.delete(f"/api/accounts/{added['id']}")

    assert [args for _, args in api.claude.runs() if args == LOGOUT] == [LOGOUT]
    assert not profile.exists()


async def test_an_account_whose_folder_is_not_nests_is_never_signed_out_or_deleted(
    api: Api,
) -> None:
    """A row pointing at the user's own folder (it can only be tampered with) is refused
    before anything runs: no sign out, nothing deleted.
    """
    claude_dir = api.ctx.paths.claude_dir
    assert claude_dir is not None
    await api.ctx.db.execute(
        "INSERT INTO engine_accounts (id, provider, profile, position, created_at, signed_in)"
        " VALUES ('0123456789ab', 'claude', ?, 1, '2026-01-01T00:00:00+00:00', 1)",
        (str(claude_dir),),
    )
    added = {"id": "0123456789ab"}

    removed = await api.http.delete(f"/api/accounts/{added['id']}")
    signed_out = await api.http.post(f"/api/accounts/{added['id']}/logout")

    assert (removed.status_code, signed_out.status_code) == (409, 409)
    assert [args for _, args in api.claude.runs() if args == LOGOUT] == []
    assert (claude_dir / "CLAUDE.md").read_text(encoding="utf-8") == "mine"


async def test_signing_in_again_prepares_the_profile_and_runs_its_login(api: Api) -> None:
    added = await add_claude(api)
    profile = profile_of(api, "claude", added["id"])
    (profile / "CLAUDE.md").unlink()

    response = await api.http.post(f"/api/accounts/{added['id']}/login")

    assert response.status_code == 202
    assert response.json()["auth_url"] is None
    assert (profile / "CLAUDE.md").is_symlink()

    async def done() -> bool:
        runs = [env for env, args in api.claude.runs() if args == LOGIN]
        return len(runs) == 2

    await until(done)


async def test_refreshing_reads_every_signed_in_account_and_is_spaced(
    api: Api, clock: FakeClock
) -> None:
    await accounts(api)
    added = await add_claude(api)
    codex = await add_codex(api)
    api.probes.replies.extend([answer(0.1), answer(0.2)])
    busy = copy.deepcopy(RATE_LIMITS)
    busy["rateLimits"] = {
        **obj(busy["rateLimits"]),
        "primary": {"usedPercent": 90, "windowDurationMins": 300, "resetsAt": None},
    }
    profile = str(profile_of(api, "codex", codex["id"]))
    api.codex.home_answers[profile]["account/rateLimits/read"] = busy

    response = await api.http.post("/api/accounts/refresh")
    soon = await api.http.post("/api/accounts/refresh")
    clock.advance(timedelta(seconds=21))
    later = await api.http.post("/api/accounts/refresh")

    listed = {a["id"]: a for a in response.json()["accounts"]}
    assert listed["claude-main"]["limits"][0]["utilization"] == 0.1
    assert listed[added["id"]]["limits"][0]["utilization"] == 0.2
    assert listed[codex["id"]]["limits"][0]["utilization"] == 0.9
    assert listed["codex-main"]["limits"][0]["utilization"] == 0.3
    assert soon.status_code == 429
    assert soon.headers["Retry-After"] == "20"
    assert later.status_code == 200
    # Only the active accounts' windows are announced as the engines'.
    assert len(await published(api, types.USAGE_UPDATED)) == 1
    assert len(await published(api, types.USAGE_PROVIDER_UPDATED)) == 2


async def test_the_schedule_reads_the_other_codex_accounts(api: Api) -> None:
    added = await add_codex(api)
    profile = str(profile_of(api, "codex", added["id"]))
    reads = api.codex.homes().count(profile)
    api.codex.home_answers[profile]["account/rateLimits/read"] = {}
    api.codex.spawn_error = None

    await api.ctx.accounts.read_other_codex()

    assert api.codex.homes().count(profile) == reads + 1


async def test_a_codex_account_that_cannot_say_its_usage_keeps_its_windows(api: Api) -> None:
    added = await add_codex(api)
    api.codex.spawn_error = OSError("gone")

    await api.ctx.accounts.read_other_codex()

    assert [w["label"] for w in by_id(await accounts(api), added["id"])["limits"]] == [
        "5 hour",
        "Weekly",
    ]


async def test_an_active_account_missing_from_the_list_falls_back_to_the_first(
    api: Api,
) -> None:
    await api.ctx.db.execute("UPDATE active_accounts SET account_id = 'gone'")
    paths = api.ctx.paths

    active = await ActiveAccounts.load(
        AccountStore(api.ctx.db, FakeClock()),
        Profiles(paths.data_dir / "profiles", FirstAccount(None, None, None)),
    )

    assert (active.id("claude"), active.id("codex")) == ("claude-main", "codex-main")
    assert (await active.prepare("claude")).env == {}


async def test_a_pages_ask_runs_on_the_active_account(api: Api) -> None:
    added = await add_claude(api)
    await api.http.put(f"/api/accounts/{added['id']}/active")
    origin = Origin(session_id="s1", repo="web", chat_title="Chat", pixie_id=None)
    page = await api.ctx.artifacts.create(origin, "html", "Ask", "<button>Ask</button>")
    api.probes.replies.append(answer())

    response = await api.http.post(f"/api/artifacts/{page.id}/ask", json={"prompt": "Hi"})

    assert response.status_code == 200
    env = api.probes.clients[-1].options.env
    assert env["CLAUDE_CONFIG_DIR"] == str(profile_of(api, "claude", added["id"]))


async def test_an_added_codex_account_that_cannot_be_asked_says_why(
    api: Api, clock: FakeClock
) -> None:
    added = await add_codex(api)
    api.codex.spawn_error = OSError("no binary")
    clock.advance(timedelta(minutes=2))

    listed = by_id(await accounts(api), added["id"])

    assert (listed["signed_in"], listed["error"], listed["email"]) == (
        None,
        "OSError",
        "work@example.com",
    )


async def test_refreshing_leaves_signed_out_accounts_alone(api: Api) -> None:
    api.claude.replies[None, STATUS] = [claude_status(None)]
    api.codex.answers["account/read"] = SIGNED_OUT
    await accounts(api)

    response = await api.http.post("/api/accounts/refresh")

    assert response.status_code == 200
    assert api.probes.clients == []
    assert api.codex.requests("account/rateLimits/read") == []


async def test_a_switch_whose_status_cannot_be_asked_still_switches(api: Api) -> None:
    added = await add_claude(api)
    profile = profile_of(api, "claude", added["id"])
    api.claude.replies[str(profile), STATUS] = [CommandError(["claude"], 1, "broken\n")]

    response = await api.http.put(f"/api/accounts/{added['id']}/active")

    assert response.status_code == 200
    assert by_id(response.json()["accounts"], added["id"])["active"] is True
    assert await published(api, types.ACCOUNT_CLAUDE) == []


async def test_a_signed_out_account_from_before_a_restart_is_removed(api: Api) -> None:
    profile = profile_of(api, "claude", "0123456789ab")
    profile.mkdir(parents=True)
    await api.ctx.db.execute(
        "INSERT INTO engine_accounts (id, provider, profile, position, created_at, signed_in)"
        " VALUES ('0123456789ab', 'claude', ?, 1, '2026-01-01T00:00:00+00:00', 0)",
        (str(profile),),
    )

    response = await api.http.delete("/api/accounts/0123456789ab")

    assert response.status_code == 200
    assert not profile.exists()
    assert api.claude.runs() == []


async def test_each_account_also_refuses_a_second_sign_in_of_its_own(api: Api) -> None:
    api.claude.gates[LOGIN] = asyncio.Event()
    claude = await api.ctx.accounts.claude_active()
    codex = await api.ctx.accounts.codex_active()
    await claude.login()
    await codex.login()

    with pytest.raises(SignInRunningError):
        await claude.login()
    with pytest.raises(CodexSignInRunningError):
        await codex.login()


CREDIT: JsonObject = {
    "id": "credit-1",
    "title": "Weekly reset",
    "description": None,
    "expiresAt": 1767225600,
    "grantedAt": 1764547200,
    "resetType": "codexRateLimits",
    "status": "available",
}


def banked(count: int, details: list[JsonObject] | None) -> JsonObject:
    summary: JsonObject = {
        "availableCount": count,
        "credits": list[JsonValue](details) if details is not None else None,
    }
    return {**RATE_LIMITS, "rateLimitResetCredits": summary}


async def test_accounts_carry_codexs_banked_resets_and_claude_none(api: Api) -> None:
    api.codex.answers["account/rateLimits/read"] = banked(2, None)
    await api.http.post("/api/usage/refresh", params={"provider": "codex"})

    claude, codex = await accounts(api)

    assert claude["banked_resets"] is None
    assert codex["banked_resets"] == {"available": 2, "credits": None}


async def test_the_banked_resets_are_read_with_details_on_the_accounts_own_home(
    api: Api,
) -> None:
    added = await add_codex(api)
    profile = str(profile_of(api, "codex", added["id"]))
    api.codex.home_answers[profile]["account/rateLimits/read"] = banked(1, [CREDIT])

    response = await api.http.get(f"/api/accounts/{added['id']}/banked-resets")

    assert response.json() == {
        "available": 1,
        "credits": [
            {
                "id": "credit-1",
                "title": "Weekly reset",
                "description": None,
                "expires_at": "2026-01-01T00:00:00Z",
            }
        ],
    }
    assert {"excludeResetCreditDetails": False} in api.codex.requests("account/rateLimits/read")
    assert api.codex.homes()[-1] == profile
    listed = by_id(await accounts(api), added["id"])
    assert listed["banked_resets"]["credits"][0]["id"] == "credit-1"


async def test_claude_accounts_have_no_banked_resets(api: Api) -> None:
    read = await api.http.get("/api/accounts/claude-main/banked-resets")
    use = await api.http.post(
        "/api/accounts/claude-main/banked-resets/use", json={"credit_id": "x"}
    )

    assert (read.status_code, use.status_code) == (409, 409)


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [
        ("reset", "reset"),
        ("nothingToReset", "nothing_to_reset"),
        ("noCredit", "no_credit"),
        ("alreadyRedeemed", "already_redeemed"),
    ],
)
async def test_using_a_banked_reset_consumes_it_on_that_account_and_reads_again(
    api: Api, answer: str, outcome: str
) -> None:
    added = await add_codex(api)
    profile = str(profile_of(api, "codex", added["id"]))
    api.codex.home_answers[profile]["account/rateLimitResetCredit/consume"] = {"outcome": answer}
    api.codex.home_answers[profile]["account/rateLimits/read"] = banked(0, [])
    changed = len(await published(api, types.ACCOUNTS_CHANGED))

    response = await api.http.post(
        f"/api/accounts/{added['id']}/banked-resets/use", json={"credit_id": "credit-1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == outcome
    assert by_id(body["accounts"], added["id"])["banked_resets"] == {
        "available": 0,
        "credits": [],
    }
    [consume] = api.codex.requests("account/rateLimitResetCredit/consume")
    assert consume["creditId"] == "credit-1"
    assert len(str(consume["idempotencyKey"])) == 36
    assert len(await published(api, types.ACCOUNTS_CHANGED)) > changed
    # Not the active account's: nothing changes for the engine.
    assert api.ctx.accounts.active_id("codex") == "codex-main"


async def test_each_use_has_its_own_idempotency_key(api: Api) -> None:
    api.codex.answers["account/rateLimitResetCredit/consume"] = {"outcome": "reset"}
    await accounts(api)

    for _ in range(2):
        response = await api.http.post(
            "/api/accounts/codex-main/banked-resets/use", json={"credit_id": "credit-1"}
        )
        assert response.status_code == 200

    first, second = api.codex.requests("account/rateLimitResetCredit/consume")
    assert first["idempotencyKey"] != second["idempotencyKey"]


async def test_a_banked_reset_is_used_only_on_a_signed_in_codex_account(api: Api) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT
    await api.http.post("/api/accounts/codex-main/logout")

    response = await api.http.post(
        "/api/accounts/codex-main/banked-resets/use", json={"credit_id": "credit-1"}
    )

    assert response.status_code == 409
    assert api.codex.requests("account/rateLimitResetCredit/consume") == []


@pytest.mark.parametrize("failure", ["error", "unknown"])
async def test_codex_failing_to_use_or_read_banked_resets_is_a_bad_gateway(
    api: Api, failure: str
) -> None:
    await accounts(api)
    if failure == "error":
        api.codex.errors["account/rateLimitResetCredit/consume"] = (-32600, "nope")
        api.codex.errors["account/rateLimits/read"] = (-32600, "nope")
    else:
        api.codex.answers["account/rateLimitResetCredit/consume"] = {"outcome": "later"}

    use = await api.http.post(
        "/api/accounts/codex-main/banked-resets/use", json={"credit_id": "credit-1"}
    )

    assert use.status_code == 502
    if failure == "error":
        read = await api.http.get("/api/accounts/codex-main/banked-resets")
        assert read.status_code == 502


async def test_banked_resets_without_windows_still_read_the_count(api: Api) -> None:
    await accounts(api)
    api.codex.answers["account/rateLimits/read"] = {
        "rateLimits": {},
        "rateLimitResetCredits": {"availableCount": 1, "credits": []},
    }

    response = await api.http.get("/api/accounts/codex-main/banked-resets")

    assert response.json() == {"available": 1, "credits": []}
    assert by_id(await accounts(api), "codex-main")["banked_resets"]["available"] == 1


async def test_no_banked_resets_reported_reads_as_none_available(api: Api) -> None:
    response = await api.http.get("/api/accounts/codex-main/banked-resets")

    assert response.json() == {"available": 0, "credits": []}


async def test_a_reset_used_still_counts_when_the_limits_cannot_be_read_after(
    api: Api,
) -> None:
    await accounts(api)
    api.codex.answers["account/rateLimitResetCredit/consume"] = {"outcome": "reset"}
    api.codex.errors["account/rateLimits/read"] = (-32600, "busy")

    response = await api.http.post(
        "/api/accounts/codex-main/banked-resets/use", json={"credit_id": "credit-1"}
    )

    assert (response.status_code, response.json()["outcome"]) == (200, "reset")
