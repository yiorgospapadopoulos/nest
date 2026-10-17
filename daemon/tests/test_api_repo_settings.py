"""Project settings B81 adds to `PATCH /api/repos/{name}`: the default branch, the push URL
and the setup time limit (D104)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import git, init_repo


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        repo = init_repo(tmp_path / "project")
        git(repo, "branch", "develop")
        await running.http.post("/api/repos", json={"path": str(repo)})
        folder = tmp_path / "notes"
        folder.mkdir()
        await running.http.post("/api/repos", json={"path": str(folder)})
        yield running


async def test_default_branch_must_be_a_local_branch(api: Api) -> None:
    changed = await api.http.patch("/api/repos/project", json={"default_branch": "develop"})
    unknown = await api.http.patch("/api/repos/project", json={"default_branch": "nope"})
    kept = await api.http.patch("/api/repos/project", json={"default_branch": None})

    assert changed.status_code == 200, changed.text
    assert changed.json()["default_branch"] == "develop"
    assert unknown.status_code == 422
    assert "nope" in unknown.json()["detail"]
    assert kept.json()["default_branch"] == "develop"


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:me/project.git",
        "https://github.com/me/project.git",
        "ssh://git@example.com/me/project.git",
        "/Users/me/remotes/project.git",
    ],
)
async def test_the_push_url_is_set_and_cleared(api: Api, url: str) -> None:
    changed = await api.http.patch("/api/repos/project", json={"remote_url": url})
    cleared = await api.http.patch("/api/repos/project", json={"remote_url": None})

    assert changed.json()["remote_url"] == url
    assert cleared.json()["remote_url"] is None


@pytest.mark.parametrize("url", ["", "   ", "not a url", "github.com"])
async def test_a_bad_push_url_is_refused(api: Api, url: str) -> None:
    response = await api.http.patch("/api/repos/project", json={"remote_url": url})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "body", [{"default_branch": "main"}, {"remote_url": "git@github.com:me/notes.git"}]
)
async def test_git_settings_are_refused_for_a_plain_folder(api: Api, body: dict[str, str]) -> None:
    response = await api.http.patch("/api/repos/notes", json=body)

    assert response.status_code == 422
    assert "not a git repository" in response.json()["detail"]


async def test_the_setup_time_limit(api: Api) -> None:
    changed = await api.http.patch("/api/repos/project", json={"setup_timeout_seconds": 1800})
    too_long = await api.http.patch("/api/repos/project", json={"setup_timeout_seconds": 86401})
    zero = await api.http.patch("/api/repos/project", json={"setup_timeout_seconds": 0})

    assert changed.json()["worktree"]["setup_timeout_seconds"] == 1800
    assert (too_long.status_code, zero.status_code) == (422, 422)
