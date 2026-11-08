"""Worktree options per project and as defaults (B141): where worktrees go, the branch
prefix, cleaning merged worktrees and checking out submodules.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.config.loader import load_settings
from nestd.config.models import WorktreeConfig, WorktreeDefaults
from nestd.paths import AppPaths
from nestd.repos.branch_map import read_branch_map
from nestd.sessions.merged_worktrees import MergedWorktrees
from nestd.sessions.models import Session, SessionState
from nestd.storage.db import Database
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import FakeRun, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import commit_file, git, init_repo
from tests.session_support import Env


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    environment.use_worktrees()
    yield environment
    await environment.manager.shutdown()


async def worktree_chat(env: Env, title: str = "first") -> Session:
    env.provider.script(reply("ok"))
    created = await env.create(title, mode="worktree")
    session = await env.reach(created.id, SessionState.IDLE)
    assert session.worktree_path is not None
    return session


def cleanup(env: Env) -> MergedWorktrees:
    return MergedWorktrees(
        repos=env.repos,
        store=env.store,
        worktrees=env.worktrees,
        remove=env.manager.remove_unused_worktree,
        bus=env.bus,
    )


async def test_branches_take_the_prefix_and_a_project_can_choose_its_own(env: Env) -> None:
    env.worktree_defaults = WorktreeDefaults(branch_prefix="gp-")
    assert str((await worktree_chat(env, "fix login")).branch).startswith("gp-fix-login-")

    env.repos.update_worktree_config("repo", WorktreeConfig(branch_prefix="team/"))
    assert str((await worktree_chat(env, "add search")).branch).startswith("team/add-search-")


async def test_worktrees_go_in_the_chosen_folder_and_are_still_nests(
    env: Env, tmp_path: Path
) -> None:
    env.worktree_defaults = WorktreeDefaults(folder=str(tmp_path / "trees"))
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    repo = env.repos.get("repo")

    assert path.parent == tmp_path / "trees" / "repo"
    assert env.worktrees.owns(repo, path)
    [branch] = [b for b in (await read_branch_map(repo, {})).branches if b.worktree is not None]
    assert branch.worktree is not None
    assert branch.worktree.owner == "nest"
    # Outside the project: nothing is added to its exclude file.
    assert "trees" not in (env.repo_path / ".git" / "info" / "exclude").read_text("utf-8")

    env.provider.script(_removes)
    await env.manager.send(session.id, "remove it", [])
    await until(lambda: not path.exists())


async def _removes(run: FakeRun) -> None:
    tool = next(tool for tool in run.spec.nest_tools if tool.name == "worktree")
    await tool.handler({"action": "remove"})
    await reply("ok")(run)


async def test_a_worktree_nest_did_not_make_is_not_its_own(env: Env, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere" / "nest-mine"
    git(env.repo_path, "worktree", "add", "-q", "-b", "mine", str(other))

    assert not env.worktrees.owns(env.repos.get("repo"), other)


async def test_submodules_are_checked_out_in_a_new_worktree(
    env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Local submodules need the file transport, which git turns off for them by default.
    for key, value in {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "protocol.file.allow",
        "GIT_CONFIG_VALUE_0": "always",
    }.items():
        monkeypatch.setenv(key, value)
    library = init_repo(tmp_path / "library")
    git(env.repo_path, "submodule", "add", "-q", str(library), "lib")
    git(env.repo_path, "commit", "-q", "-m", "add the library")
    env.worktree_defaults = WorktreeDefaults(submodules=True)

    session = await worktree_chat(env)

    assert session.worktree_path is not None
    assert (session.worktree_path / "lib" / "README.md").is_file()


async def test_merged_worktrees_go_and_the_rest_stay(env: Env) -> None:
    env.repos.update_worktree_config("repo", WorktreeConfig(clean_merged=True))
    merged, unmerged, untouched, dirty, open_chat = [
        await worktree_chat(env, title) for title in ("one", "two", "three", "four", "five")
    ]
    for session in (merged, unmerged, dirty, open_chat):
        assert session.worktree_path is not None
        commit_file(session.worktree_path, f"{session.title}.txt")
    assert dirty.worktree_path is not None
    (dirty.worktree_path / "notes.txt").write_text("mine\n", encoding="utf-8")
    for session in (merged, dirty, open_chat):
        git(env.repo_path, "merge", "-q", "--no-ff", "-m", "merge", str(session.branch))
    for session in (merged, unmerged, untouched, dirty):
        await env.manager.close(session.id, remove_worktree=False)

    removed = await cleanup(env).sweep(env.repos.get("repo"))

    assert removed == [merged.worktree_path]
    for session in (unmerged, untouched, dirty, open_chat):
        assert session.worktree_path is not None
        assert session.worktree_path.is_dir()
    assert str(merged.branch) in git(env.repo_path, "branch", "--list", str(merged.branch))


async def test_merged_worktrees_stay_unless_the_project_asks(env: Env) -> None:
    session = await worktree_chat(env)
    assert session.worktree_path is not None
    commit_file(session.worktree_path, "done.txt")
    git(env.repo_path, "merge", "-q", "--no-ff", "-m", "merge", str(session.branch))
    await env.manager.close(session.id, remove_worktree=False)

    assert await cleanup(env).sweep(env.repos.get("repo")) == []
    assert session.worktree_path.is_dir()


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def test_the_defaults_and_a_projects_choices_are_saved(api: Api, tmp_path: Path) -> None:
    defaults = {"folder": "~/trees", "branch_prefix": "gp/", "clean_merged": True}

    saved = await api.http.put("/api/worktrees/settings", json=defaults)
    chosen = await api.http.patch("/api/repos/repo", json={"submodules": True, "folder": "/wt"})
    cleared = await api.http.patch("/api/repos/repo", json={"folder": None})

    assert saved.json() == {**defaults, "submodules": False}
    assert (await api.http.get("/api/worktrees/settings")).json() == saved.json()
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    assert load_settings(paths).worktrees.branch_prefix == "gp/"
    assert chosen.json()["worktree"]["folder"] == "/wt"
    assert cleared.json()["worktree"] == {**chosen.json()["worktree"], "folder": None}
    assert cleared.json()["worktree"]["submodules"] is True


@pytest.mark.parametrize(
    "body", [{"branch_prefix": "../x"}, {"branch_prefix": "-x"}, {"folder": "relative/path"}]
)
async def test_bad_choices_are_refused(api: Api, body: dict[str, str]) -> None:
    assert (await api.http.put("/api/worktrees/settings", json=body)).status_code == 422
    assert (await api.http.patch("/api/repos/repo", json=body)).status_code == 422
