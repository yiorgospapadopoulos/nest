"""Claude Code in Settings (D104): the account through `claude auth`, and finding or
installing a standalone Claude Code. Every command is faked."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from nestd.claude_code.cli import INSTALL_COMMAND, ClaudeLocations
from nestd.events import types
from nestd.gitops.runner import CommandError
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_claude import install_standalone, locations
from tests.fakes import FakeClock, FakeSecretStore

SIGNED_IN = {
    "loggedIn": True,
    "authMethod": "claude.ai",
    "apiProvider": "firstParty",
    "email": "me@example.com",
    "orgId": "0000",
    "orgName": "My Organization",
    "subscriptionType": "pro",
}
SIGNED_OUT = {"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"}
STATUS = ("auth", "status", "--json")


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


def where(api: Api) -> ClaudeLocations:
    return api.ctx.claude_code.locations


async def published(api: Api, event_type: str) -> list[dict[str, Any]]:
    rows = await api.ctx.db.fetch_all(
        "SELECT payload FROM events WHERE type = ? ORDER BY id", (event_type,)
    )
    return [json.loads(row["payload"]) for row in rows]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/accounts/claude"),
        ("POST", "/api/accounts/claude/login"),
        ("POST", "/api/accounts/claude/logout"),
        ("GET", "/api/claude-code"),
        ("POST", "/api/claude-code/install"),
    ],
)
async def test_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_account_status_uses_the_bundled_cli_without_a_standalone(api: Api) -> None:
    api.claude.script(*STATUS, reply=json.dumps(SIGNED_IN))

    body = (await api.http.get("/api/accounts/claude")).json()

    assert body == {
        "signed_in": True,
        "email": "me@example.com",
        "organization": "My Organization",
        "plan": "Claude Pro",
        "method": "claude.ai",
        "checked_at": "2026-01-01T12:00:00Z",
    }
    assert api.claude.args_of(where(api).bundled) == [STATUS]


async def test_account_status_prefers_the_standalone_cli(api: Api) -> None:
    standalone = install_standalone(where(api))
    api.claude.script(*STATUS, reply=json.dumps(SIGNED_OUT))

    body = (await api.http.get("/api/accounts/claude")).json()

    assert (body["signed_in"], body["email"], body["plan"], body["method"]) == (
        False,
        None,
        None,
        "none",
    )
    assert api.claude.args_of(standalone) == [STATUS]


@pytest.mark.parametrize(
    "reply",
    [
        CommandError(["claude"], 1, "something broke\n"),
        FileNotFoundError(2, "No such file"),
        "not json",
    ],
)
async def test_a_failing_status_is_a_bad_gateway(api: Api, reply: str | Exception) -> None:
    api.claude.script(*STATUS, reply=reply)

    response = await api.http.get("/api/accounts/claude")

    assert response.status_code == 502
    assert response.json()["detail"]


async def test_sign_in_runs_in_the_background_one_at_a_time(api: Api) -> None:
    login = ("auth", "login", "--claudeai")
    gate = asyncio.Event()
    api.claude.gates[login] = gate
    api.claude.script(*login, reply="Login successful.\n")
    api.claude.script(*STATUS, reply=json.dumps(SIGNED_IN))

    started = await api.http.post("/api/accounts/claude/login")
    again = await api.http.post("/api/accounts/claude/login")
    gate.set()

    assert started.status_code == 202
    assert again.status_code == 409

    async def announced() -> bool:
        return len(await published(api, types.ACCOUNT_CLAUDE)) == 1

    await until(announced)
    [event] = await published(api, types.ACCOUNT_CLAUDE)
    assert (event["signed_in"], event["email"], event["error"]) == (True, "me@example.com", None)
    assert api.claude.args_of(where(api).bundled) == [login, STATUS]


async def test_a_failed_sign_in_is_announced_with_its_error(api: Api) -> None:
    api.claude.script(
        "auth", "login", "--claudeai", reply=CommandError(["claude"], 1, "Login cancelled\n")
    )
    api.claude.script(*STATUS, reply=json.dumps(SIGNED_OUT))

    assert (await api.http.post("/api/accounts/claude/login")).status_code == 202

    async def announced() -> bool:
        return len(await published(api, types.ACCOUNT_CLAUDE)) == 1

    await until(announced)
    [event] = await published(api, types.ACCOUNT_CLAUDE)
    assert (event["signed_in"], event["error"]) == (False, "Login cancelled")


async def test_a_sign_in_whose_status_fails_is_announced_signed_out(api: Api) -> None:
    api.claude.script("auth", "login", "--claudeai", reply="ok\n")

    assert (await api.http.post("/api/accounts/claude/login")).status_code == 202

    async def announced() -> bool:
        return len(await published(api, types.ACCOUNT_CLAUDE)) == 1

    await until(announced)
    [event] = await published(api, types.ACCOUNT_CLAUDE)
    assert event["signed_in"] is False
    assert "unscripted" in event["error"]


async def test_sign_out(api: Api) -> None:
    api.claude.script("auth", "logout", reply="Successfully logged out.\n")
    api.claude.script(*STATUS, reply=json.dumps(SIGNED_OUT))

    response = await api.http.post("/api/accounts/claude/logout")

    assert response.status_code == 200
    assert response.json()["signed_in"] is False
    [event] = await published(api, types.ACCOUNT_CLAUDE)
    assert (event["signed_in"], event["error"]) == (False, None)


async def test_a_failed_sign_out_is_a_bad_gateway(api: Api) -> None:
    api.claude.script("auth", "logout", reply=CommandError(["claude"], 1, "\n"))

    response = await api.http.post("/api/accounts/claude/logout")

    assert response.status_code == 502
    assert response.json()["detail"] == "claude auth logout failed"
    assert await published(api, types.ACCOUNT_CLAUDE) == []


async def test_claude_code_not_installed(api: Api) -> None:
    assert (await api.http.get("/api/claude-code")).json() == {
        "installed": False,
        "path": None,
        "version": None,
        "bundled_version": "2.1.286",
    }


async def test_a_standalone_install_is_found_with_its_version(api: Api) -> None:
    standalone = install_standalone(where(api))
    api.claude.script("--version", reply="2.1.285 (Claude Code)\n")

    body = (await api.http.get("/api/claude-code")).json()

    assert body == {
        "installed": True,
        "path": str(standalone),
        "version": "2.1.285",
        "bundled_version": "2.1.286",
    }


async def test_a_standalone_whose_version_fails_has_none(api: Api) -> None:
    install_standalone(where(api))

    body = (await api.http.get("/api/claude-code")).json()

    assert (body["installed"], body["version"]) == (True, None)


def test_the_path_search_and_files_that_are_not_programs(tmp_path: Path) -> None:
    where = locations(tmp_path)
    folder = tmp_path / "bin"
    folder.mkdir()
    program = folder / "claude"
    program.write_text("#!/bin/sh\n", encoding="utf-8")
    plain = where.candidates[0]
    plain.parent.mkdir(parents=True)
    plain.write_text("not executable", encoding="utf-8")

    assert where.standalone() is None
    program.chmod(0o755)
    on_path = ClaudeLocations(
        search_path=str(folder),
        candidates=where.candidates,
        bundled=where.bundled,
        bundled_version="1",
    )
    assert on_path.standalone() == program
    # The SDK's own copy on the PATH is not a standalone install.
    bundled = ClaudeLocations(
        search_path=str(folder), candidates=(), bundled=program, bundled_version="1"
    )
    assert bundled.standalone() is None


def test_default_locations(tmp_path: Path) -> None:
    where = ClaudeLocations.default(tmp_path, {"PATH": "/usr/bin"})

    assert where.search_path == "/usr/bin"
    assert where.candidates[:2] == (
        tmp_path / ".local" / "bin" / "claude",
        tmp_path / ".claude" / "local" / "claude",
    )
    assert where.bundled.name == "claude"
    assert where.bundled.parent.name == "_bundled"
    assert where.bundled_version.count(".") == 2
    assert ClaudeLocations.default(tmp_path, {}).search_path == ""


async def test_install_runs_the_official_installer_and_announces_the_result(
    api: Api,
) -> None:
    gate = asyncio.Event()
    installer = tuple(INSTALL_COMMAND[1:])
    api.claude.gates[installer] = gate

    api.claude.script(*installer, reply="Claude Code installed\n")
    api.claude.script("--version", reply="2.1.290 (Claude Code)\n")

    started = await api.http.post("/api/claude-code/install")
    running = await api.http.post("/api/claude-code/install")
    install_standalone(where(api))
    gate.set()

    assert started.status_code == 202
    assert running.status_code == 409

    async def done() -> bool:
        return len(await published(api, types.CLAUDE_CODE_UPDATED)) == 1

    await until(done)
    assert await published(api, types.CLAUDE_CODE_INSTALL) == [
        {"state": "running", "message": None},
        {"state": "done", "message": "Claude Code installed"},
    ]
    [updated] = await published(api, types.CLAUDE_CODE_UPDATED)
    assert (updated["installed"], updated["version"]) == (True, "2.1.290")
    assert api.claude.calls[0] == INSTALL_COMMAND
    # Installed now: no second install.
    assert (await api.http.post("/api/claude-code/install")).status_code == 409


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (CommandError(["bash"], 1, "curl: (6) Could not resolve host\n"), "curl: (6)"),
        ("Done\n", "the installer finished but Claude Code was not found"),
    ],
)
async def test_a_failed_install_is_announced(
    api: Api, reply: str | Exception, message: str
) -> None:
    api.claude.script(*INSTALL_COMMAND[1:], reply=reply)

    assert (await api.http.post("/api/claude-code/install")).status_code == 202

    async def done() -> bool:
        return len(await published(api, types.CLAUDE_CODE_UPDATED)) == 1

    await until(done)
    events = await published(api, types.CLAUDE_CODE_INSTALL)
    assert events[-1]["state"] == "failed"
    assert message in events[-1]["message"]


async def test_a_sign_in_or_install_in_progress_is_stopped_with_the_daemon(api: Api) -> None:
    api.claude.gates[("auth", "login", "--claudeai")] = asyncio.Event()
    api.claude.gates[tuple(INSTALL_COMMAND[1:])] = asyncio.Event()
    await api.http.post("/api/accounts/claude/login")
    await api.http.post("/api/claude-code/install")
    await until(lambda: len(api.claude.calls) == 2)

    await api.ctx.claude_account.stop()
    await api.ctx.claude_code.stop()

    assert await published(api, types.ACCOUNT_CLAUDE) == []
    assert await published(api, types.CLAUDE_CODE_UPDATED) == []
