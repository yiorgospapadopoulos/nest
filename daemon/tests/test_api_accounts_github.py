"""The GitHub account in Settings: the user's `gh` login, never its token (D104)."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.gitops.runner import CommandError
from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


def gh_calls(api: Api) -> list[tuple[str, ...]]:
    return [call for call in api.runner.calls if call[:2] == ("gh", "api")]


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/api/accounts/github"), ("POST", "/api/accounts/github/check")]
)
async def test_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_signed_in_status_is_cached_until_checked_again(api: Api, clock: FakeClock) -> None:
    api.runner.outputs["gh api"] = "octocat\n"

    first = (await api.http.get("/api/accounts/github")).json()
    clock.advance(timedelta(minutes=5))
    cached = (await api.http.get("/api/accounts/github")).json()

    assert first == {
        "state": "signed_in",
        "login": "octocat",
        "checked_at": clock.now().replace(minute=0).isoformat().replace("+00:00", "Z"),
    }
    assert cached == first
    assert gh_calls(api) == [("gh", "api", "user", "--jq", ".login")]

    api.runner.failures["gh api"] = CommandError(
        ["gh", "api", "user"], 4, "To get started with GitHub CLI, please run:  gh auth login\n"
    )
    checked = (await api.http.post("/api/accounts/github/check")).json()

    assert (checked["state"], checked["login"]) == ("signed_out", None)
    assert checked["checked_at"].startswith("2026-01-01T12:05")


async def test_an_old_status_is_checked_again(api: Api, clock: FakeClock) -> None:
    api.runner.outputs["gh api"] = "octocat\n"
    await api.http.get("/api/accounts/github")
    clock.advance(timedelta(hours=1))
    api.runner.outputs["gh api"] = "hubot\n"

    assert (await api.http.get("/api/accounts/github")).json()["login"] == "hubot"


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError(2, "No such file or directory: 'gh'"),
        CommandError(["gh", "api", "user"], 1, "error connecting to api.github.com\n"),
        CommandError(["gh", "api", "user"], None, "timed out after 300 seconds"),
    ],
)
async def test_gh_missing_or_unreachable_is_unavailable(api: Api, failure: Exception) -> None:
    api.runner.failures["gh api"] = failure

    body = (await api.http.post("/api/accounts/github/check")).json()

    assert (body["state"], body["login"]) == ("unavailable", None)


async def test_a_login_gh_does_not_print_is_signed_out(api: Api) -> None:
    api.runner.outputs["gh api"] = "\n"

    body = (await api.http.post("/api/accounts/github/check")).json()

    assert (body["state"], body["login"]) == ("signed_out", None)
