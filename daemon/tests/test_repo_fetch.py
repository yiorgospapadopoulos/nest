"""The branch map's reload (B131): `POST /api/repos/{name}/refresh` fetches every remote
into its own tracking refs and changes nothing else, and `POST .../remote-branches` makes
a local branch from a remote-only one.
"""

import asyncio
import shutil
import stat
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.config.models import RepoConfig
from nestd.events import types
from nestd.gitops.safety import RepoSetting, fetch_blockers
from nestd.repos import fetching
from nestd.worktrees import manager
from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import git, init_repo

DEAD = "ssh://nonexistent.invalid/x.git"


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return (tmp_path / "repo").resolve()


def bare_copy(repo: Path, path: Path, name: str = "origin") -> Path:
    """A bare copy of `repo`, added as the remote `name` without fetching it."""
    git(repo, "clone", "-q", "--bare", ".", str(path))
    git(repo, "remote", "add", name, str(path))
    return path


def new_commit(bare: Path, branch: str, start: str = "main") -> str:
    """A new commit on `branch` of a bare repository."""
    commit = git(bare, "commit-tree", f"{start}^{{tree}}", "-p", start, "-m", "new").strip()
    git(bare, "update-ref", f"refs/heads/{branch}", commit)
    return commit


def refs(repo: Path, prefix: str = "refs/") -> str:
    return git(repo, "for-each-ref", "--format=%(refname) %(objectname)", prefix)


async def refresh(api: Api) -> list[dict[str, JsonValue]]:
    response = await api.http.post("/api/repos/repo/refresh")
    assert response.status_code == 200, response.text
    return response.json()["remotes"]


def marker_hook(repo: Path, marker: Path) -> None:
    hook = repo / ".git" / "hooks" / "reference-transaction"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f'#!/bin/sh\necho ran >> "{marker}"\n', encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)


async def test_a_fetch_changes_only_that_remotes_tracking_refs(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    bare = bare_copy(repo, tmp_path / "origin.git")
    tip = new_commit(bare, "main")
    new_commit(bare, "feat/x")
    git(bare, "tag", "v1", "main")
    # A hostile setting: a plain fetch would write straight over local branches.
    git(repo, "config", "--replace-all", "remote.origin.fetch", "+refs/heads/*:refs/heads/*")
    git(repo, "branch", "local")
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    heads = refs(repo, "refs/heads/")
    head = git(repo, "rev-parse", "HEAD")

    assert await refresh(api) == [{"name": "origin", "error": None}]

    assert refs(repo, "refs/heads/") == heads
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "rev-parse", "refs/remotes/origin/main").strip() == tip
    assert "refs/remotes/origin/feat/x" in refs(repo)
    assert refs(repo, "refs/tags/") == ""
    assert (repo / "README.md").read_text(encoding="utf-8") == "dirty\n"
    assert not (repo / ".git" / "FETCH_HEAD").exists()


async def test_a_remote_branch_deleted_there_stops_showing_and_only_that(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    bare = bare_copy(repo, tmp_path / "origin.git")
    new_commit(bare, "old")
    await refresh(api)
    git(bare, "update-ref", "-d", "refs/heads/old")
    git(repo, "update-ref", "refs/remotes/other/keep", "HEAD")
    git(repo, "branch", "old")
    git(repo, "tag", "keep")

    await refresh(api)

    assert "refs/remotes/origin/old" not in refs(repo)
    assert "refs/remotes/other/keep" in refs(repo)
    assert "refs/heads/old" in refs(repo)
    assert "refs/tags/keep" in refs(repo)


async def test_after_a_fetch_the_map_shows_behind_counts_and_remote_rows(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    bare = bare_copy(repo, tmp_path / "origin.git")
    git(repo, "fetch", "-q", "origin")
    git(repo, "branch", "--set-upstream-to=origin/main", "main")
    new_commit(bare, "main")
    new_commit(bare, "feat/x")

    await refresh(api)
    payload = (await api.http.get("/api/repos/repo/branch-map")).json()

    assert payload["branches"][0]["behind"] == 1
    assert payload["remote_branches"] == [{"remote": "origin", "name": "feat/x"}]


async def test_a_failing_remote_does_not_stop_the_others(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    bare = bare_copy(repo, tmp_path / "origin.git")
    tip = new_commit(bare, "main")
    git(repo, "remote", "add", "dead", str(tmp_path / "missing.git"))

    remotes = await refresh(api)

    assert remotes[1] == {"name": "origin", "error": None}
    assert remotes[0]["name"] == "dead"
    assert "missing.git" in str(remotes[0]["error"])
    assert git(repo, "rev-parse", "refs/remotes/origin/main").strip() == tip


async def test_with_every_remote_failing_the_map_still_reads(api: Api, repo: Path) -> None:
    git(repo, "remote", "add", "origin", "/no/such/remote.git")
    git(repo, "remote", "add", "other", "/no/such/other.git")
    git(repo, "update-ref", "refs/remotes/origin/known", "HEAD")

    remotes = await refresh(api)
    payload = (await api.http.get("/api/repos/repo/branch-map")).json()

    assert [remote["error"] is not None for remote in remotes] == [True, True]
    assert payload["branches"][0]["name"] == "main"
    assert payload["remote_branches"] == [{"remote": "origin", "name": "known"}]


async def test_no_remotes_is_an_empty_report(api: Api, repo: Path) -> None:
    assert await refresh(api) == []


@pytest.mark.parametrize("breakage", ["config", "objects"])
async def test_a_broken_repo_is_a_conflict_with_gits_reason(
    api: Api, repo: Path, breakage: str
) -> None:
    if breakage == "config":
        with (repo / ".git" / "config").open("a", encoding="utf-8") as config:
            config.write("[bad\n")
    else:
        shutil.rmtree(repo / ".git" / "objects")

    response = await api.http.post("/api/repos/repo/refresh")

    assert response.status_code == 409
    assert list(response.json()) == ["detail"]
    assert response.json()["detail"].startswith("fatal: ")
    assert "\n" not in response.json()["detail"]


async def test_tracking_on_a_broken_repo_is_a_conflict_with_gits_reason(
    api: Api, repo: Path
) -> None:
    with (repo / ".git" / "config").open("a", encoding="utf-8") as config:
        config.write("[bad\n")

    response = await api.http.post(
        "/api/repos/repo/remote-branches", json={"remote": "origin", "name": "wip"}
    )

    assert response.status_code == 409
    assert response.json()["detail"].startswith("fatal: ")


async def test_error_text_is_one_line_without_credentials(api: Api, repo: Path) -> None:
    git(repo, "remote", "add", "origin", "http://user:secret@127.0.0.1:9/x.git")

    remote = (await refresh(api))[0]

    assert "secret" not in str(remote["error"])
    assert "\n" not in str(remote["error"])


@pytest.mark.parametrize("scheme", ["git", "http"])
async def test_a_hung_remote_is_cut_off_and_holds_up_no_other(
    api: Api, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scheme: str
) -> None:
    monkeypatch.setattr(fetching, "FETCH_TIME_LIMIT", 1.0)
    bare = bare_copy(repo, tmp_path / "origin.git")
    tip = new_commit(bare, "main")
    silent: list[asyncio.StreamWriter] = []

    async def never_answer(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        silent.append(writer)

    server = await asyncio.start_server(never_answer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    git(repo, "remote", "add", "hung", f"{scheme}://127.0.0.1:{port}/x.git")

    async with server:
        try:
            remotes = await asyncio.wait_for(refresh(api), 10)
        finally:
            for writer in silent:
                writer.close()

    assert remotes[0] == {"name": "hung", "error": "timed out after 1 seconds"}
    assert remotes[1] == {"name": "origin", "error": None}
    assert git(repo, "rev-parse", "refs/remotes/origin/main").strip() == tip


async def test_a_repo_program_stops_the_fetch_and_is_not_run(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "ran"
    script = tmp_path / "evil.sh"
    script.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 1\n', encoding="utf-8")
    script.chmod(0o755)
    git(repo, "config", "core.sshCommand", str(script))
    git(repo, "remote", "add", "origin", "ssh://example.invalid/x.git")
    git(repo, "remote", "add", "other", "ssh://example.invalid/y.git")

    remotes = await refresh(api)
    map_reply = await api.http.get("/api/repos/repo/branch-map")

    reason = "the project's git settings stop a fetch: core.sshcommand (runs a program)"
    assert remotes == [{"name": "origin", "error": reason}, {"name": "other", "error": reason}]
    assert not marker.exists()
    assert map_reply.status_code == 200


async def test_a_fetch_runs_no_hook(api: Api, repo: Path, tmp_path: Path) -> None:
    bare = bare_copy(repo, tmp_path / "origin.git")
    new_commit(bare, "main")
    marker = tmp_path / "ran"
    marker_hook(repo, marker)

    assert await refresh(api) == [{"name": "origin", "error": None}]

    assert not marker.exists()


@pytest.mark.parametrize("remote", ["*", "a:b", "-x", "a..b"])
async def test_a_remote_name_that_could_change_the_refspec_is_not_fetched(
    api: Api, repo: Path, tmp_path: Path, remote: str
) -> None:
    bare = bare_copy(repo, tmp_path / "origin.git")
    git(repo, "config", f"remote.{remote}.url", str(bare))
    before = refs(repo, "refs/heads/")

    remotes = await refresh(api)

    assert {"name": remote, "error": "Nest cannot fetch a remote with this name"} in remotes
    assert f"refs/remotes/{remote}/" not in refs(repo)
    assert refs(repo, "refs/heads/") == before


async def test_a_refresh_announces_the_map(
    api: Api, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    announced: list[Mapping[str, JsonValue]] = []
    publish = api.ctx.bus.publish_ephemeral

    async def record(
        event_type: str, payload: Mapping[str, JsonValue], session_id: str | None = None
    ) -> object:
        if event_type == types.REPO_BRANCHES_CHANGED:
            announced.append(payload)
        return await publish(event_type, payload, session_id)

    monkeypatch.setattr(api.ctx.bus, "publish_ephemeral", record)

    await refresh(api)

    assert announced == [{"name": "repo"}]


def test_fetch_blockers_cover_what_a_fetch_reaches_and_nothing_else() -> None:
    def blocked(key: str, value: str = "x") -> bool:
        return bool(fetch_blockers([RepoSetting("local", key, value)]))

    for key in (
        "core.sshCommand",
        "core.gitProxy",
        "core.askPass",
        "core.alternateRefsCommand",
        "ssh.variant",
        "credential.helper",
        "url.https://evil/.insteadOf",
        "http.proxy",
        "remote.origin.uploadpack",
        "remote.origin.proxy",
        "remote.origin.vcs",
        "protocol.file.allow",
        "hook.foo.command",
        "fetch.bundleURI",
        "bundle.version",
    ):
        assert blocked(key), key
    for key in (
        "diff.x.textconv",
        "filter.evil.clean",
        "gpg.program",
        "core.pager",
        "http.postBuffer",
        "protocol.version",
        "remote.origin.url",
    ):
        assert not blocked(key), key


