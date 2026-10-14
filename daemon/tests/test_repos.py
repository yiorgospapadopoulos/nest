import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from harness.config.loader import load_repos
from harness.config.models import RepoConfig, WorktreeConfig
from harness.events import types
from harness.events.bus import EventBus
from harness.gitops.runner import GitError
from harness.paths import AppPaths
from harness.repos import service as service_module
from harness.repos.service import (
    InvalidRepoError,
    NotAGitRepositoryError,
    RepoExistsError,
    RepoFolderMissingError,
    RepoNotFoundError,
    RepoService,
    is_link_candidate,
)
from harness.storage.db import Database
from tests.fakes import FakeClock
from tests.git_support import commit_file, git, init_repo, with_origin


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    result.ensure()
    return result


@pytest.fixture
def service(paths: AppPaths, db: Database, clock: FakeClock) -> RepoService:
    return RepoService(paths, bus=EventBus(db, clock))


async def updated_events(db: Database) -> list[object]:
    rows = await db.fetch_all("SELECT payload FROM events WHERE type = ?", (types.REPO_UPDATED,))
    return [json.loads(row["payload"]) for row in rows]


async def test_register_saves_config_with_folder_name_and_current_branch(
    service: RepoService, paths: AppPaths, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "My Project!", branch="trunk")

    registered = await service.register(repo)

    assert registered == RepoConfig(name="My-Project-", path=repo.resolve(), default_branch="trunk")
    assert load_repos(paths) == [registered]
    assert service.list_repos() == [registered]
    assert service.get("My-Project-") == registered


async def test_register_prefers_origin_head_and_explicit_name(
    service: RepoService, tmp_path: Path
) -> None:
    origin = init_repo(tmp_path / "origin", branch="develop")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(origin), str(clone))
    git(clone, "checkout", "-q", "-b", "feature")

    registered = await service.register(clone, name="app")

    assert registered.name == "app"
    assert registered.default_branch == "develop"


async def test_register_records_the_origin_push_url(service: RepoService, tmp_path: Path) -> None:
    """D050: the URL harness pushes to, recorded before any agent ran in the repo."""
    repo = init_repo(tmp_path / "repo")
    origin = with_origin(repo, tmp_path / "origin.git")

    assert (await service.register(repo)).remote_url == str(origin)


async def test_register_leaves_credentials_out_of_the_remote_url(
    service: RepoService, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "remote", "add", "origin", "https://me:secret@example.com/me/repo.git")

    assert (await service.register(repo)).remote_url == "https://example.com/me/repo.git"


async def test_register_records_no_remote_url_without_exactly_one(
    service: RepoService, tmp_path: Path
) -> None:
    alone = init_repo(tmp_path / "alone")
    mirrored = init_repo(tmp_path / "mirrored")
    git(mirrored, "remote", "add", "origin", "https://example.com/a.git")
    git(mirrored, "config", "--add", "remote.origin.pushurl", "https://example.com/a.git")
    git(mirrored, "config", "--add", "remote.origin.pushurl", "https://example.com/b.git")

    assert (await service.register(alone)).remote_url is None
    assert (await service.register(mirrored)).remote_url is None


async def test_a_confirmed_remote_url_is_saved(
    service: RepoService, paths: AppPaths, tmp_path: Path
) -> None:
    await service.register(init_repo(tmp_path / "repo"))

    confirmed = service.confirm_remote_url("repo", "https://example.com/me/repo.git")

    assert confirmed.remote_url == "https://example.com/me/repo.git"
    assert load_repos(paths) == [confirmed]


async def test_register_falls_back_to_main_on_detached_head(
    service: RepoService, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "repo", branch="work")
    git(repo, "checkout", "-q", "--detach")

    assert (await service.register(repo)).default_branch == "main"


async def test_register_slugifies_names_that_would_be_empty(
    service: RepoService, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "...")

    assert (await service.register(repo)).name == "repo"


async def test_register_rejects_missing_dirs_and_subdirectories(
    service: RepoService, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "sub").mkdir()

    with pytest.raises(InvalidRepoError, match="not a directory"):
        await service.register(tmp_path / "missing")
    with pytest.raises(InvalidRepoError, match="not the root of a git work tree"):
        await service.register(repo / "sub")
    with pytest.raises(InvalidRepoError, match="not an absolute path"):
        await service.register(Path("relative/repo"))


async def test_register_a_folder_outside_git_as_a_plain_folder(
    service: RepoService, paths: AppPaths, tmp_path: Path
) -> None:
    folder = tmp_path / "Notes folder"
    folder.mkdir()
    (folder / "todo.md").write_text("- write\n", encoding="utf-8")
    git_repo = await service.register(init_repo(tmp_path / "code"))

    plain = await service.register(folder)

    assert plain == RepoConfig(
        name="Notes-folder", path=folder.resolve(), git=False, default_branch=None
    )
    assert plain.model_dump(mode="json")["default_branch"] is None
    assert service.list_repos() == [plain, git_repo]
    # Only plain folders write the key; nothing was run in the folder.
    assert "git = false" in (paths.repos_dir / "Notes-folder.toml").read_text(encoding="utf-8")
    assert "git =" not in (paths.repos_dir / "code.toml").read_text(encoding="utf-8")
    assert not (folder / ".git").exists()


def test_repo_files_without_the_git_key_are_git_repos(paths: AppPaths, tmp_path: Path) -> None:
    (paths.repos_dir / "old.toml").write_text(
        f'name = "old"\npath = "{tmp_path}"\ndefault_branch = "trunk"\n', encoding="utf-8"
    )
    (paths.repos_dir / "notes.toml").write_text(
        f'name = "notes"\npath = "{tmp_path}"\ngit = false\ndefault_branch = "main"\n',
        encoding="utf-8",
    )

    notes, old = load_repos(paths)

    assert (old.git, old.default_branch) == (True, "trunk")
    # A plain folder never has a branch, whatever the file says.
    assert (notes.git, notes.default_branch) == (False, None)


async def test_register_reports_other_git_failures(
    service: RepoService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing(args: Sequence[str], cwd: Path) -> str:
        raise GitError(args, 128, "fatal: detected dubious ownership in repository")

    monkeypatch.setattr(service_module, "run_hardened_git", failing)

    with pytest.raises(InvalidRepoError, match="dubious ownership"):
        await service.register(tmp_path)
    assert service.list_repos() == []


async def test_a_plain_folder_becomes_a_git_repo_once_initialized(
    service: RepoService, paths: AppPaths, db: Database, tmp_path: Path
) -> None:
    folder = tmp_path / "notes"
    folder.mkdir()
    await service.register(folder)

    unchanged = await service.current("notes")
    (folder / ".git").mkdir()  # not a repository yet
    still = await service.list_current()
    shutil.rmtree(folder / ".git")
    git(folder, "init", "-q", "-b", "main")
    became = await service.current("notes")
    again = await service.list_current()

    assert (unchanged.git, still[0].git) == (False, False)
    assert became == RepoConfig(name="notes", path=folder.resolve(), default_branch="main")
    assert again == [became]
    assert load_repos(paths) == [became]
    assert "git =" not in (paths.repos_dir / "notes.toml").read_text(encoding="utf-8")
    assert await updated_events(db) == [{"name": "notes", "repo": became.model_dump(mode="json")}]


async def test_a_detected_repo_takes_its_current_branch(
    service: RepoService, tmp_path: Path
) -> None:
    folder = tmp_path / "notes"
    folder.mkdir()
    await service.register(folder)
    git(folder, "init", "-q", "-b", "drafts")

    assert (await service.list_current())[0].default_branch == "drafts"


async def test_a_plain_folder_inside_a_new_repo_stays_plain(
    service: RepoService, tmp_path: Path
) -> None:
    parent = tmp_path / "parent"
    folder = parent / "notes"
    folder.mkdir(parents=True)
    await service.register(folder)
    git(parent, "init", "-q")
    # An empty `.git` folder: git finds the parent's work tree instead.
    (folder / ".git").mkdir()
    inside = await service.current("notes")
    # A `.git` file pointing nowhere does not make it a root either.
    (folder / ".git").rmdir()
    (folder / ".git").write_text("gitdir: /nowhere\n", encoding="utf-8")

    assert (inside.git, (await service.current("notes")).git) == (False, False)


async def test_git_checks_by_repo_name(service: RepoService, tmp_path: Path) -> None:
    folder = tmp_path / "notes"
    folder.mkdir()
    await service.register(folder)
    await service.register(init_repo(tmp_path / "code"))

    assert await service.has_git("code") is True
    assert await service.has_git("notes") is False
    # Unknown repos are left to the git commands that follow, as before plain folders.
    assert await service.has_git("gone") is True
    await service.require_git("code")
    with pytest.raises(NotAGitRepositoryError) as raised:
        await service.require_git("notes")
    assert raised.value.status_code == 409
    assert raised.value.payload() == {
        "detail": "notes is not a git repository",
        "code": "not_a_git_repository",
    }
    with pytest.raises(NotAGitRepositoryError):
        await service.suggest_links("notes")
    with pytest.raises(RepoNotFoundError):
        await service.current("gone")


async def test_detection_without_an_event_bus(paths: AppPaths, tmp_path: Path) -> None:
    quiet = RepoService(paths)
    folder = tmp_path / "notes"
    folder.mkdir()
    await quiet.register(folder)
    git(folder, "init", "-q", "-b", "main")

    assert (await quiet.current("notes")).git is True


async def test_register_rejects_invalid_explicit_names(
    service: RepoService, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "repo")

    with pytest.raises(InvalidRepoError, match="invalid repo name"):
        await service.register(repo, name="../escape")


async def test_register_rejects_duplicate_names_and_paths(
    service: RepoService, tmp_path: Path
) -> None:
    first = init_repo(tmp_path / "a" / "same")
    second = init_repo(tmp_path / "b" / "same")
    await service.register(first)

    with pytest.raises(RepoExistsError, match="repo 'same' already exists"):
        await service.register(second)
    with pytest.raises(RepoExistsError, match="already registered as 'same'"):
        await service.register(first, name="other")
    assert (await service.register(second, name="second")).name == "second"


def test_get_unknown_repo(service: RepoService) -> None:
    with pytest.raises(RepoNotFoundError, match="unknown repo 'nope'"):
        service.get("nope")


async def test_update_worktree_config_persists(
    service: RepoService, paths: AppPaths, tmp_path: Path
) -> None:
    await service.register(init_repo(tmp_path / "repo"))
    config = WorktreeConfig(default=False, link=[".env"], setup=["make"], setup_timeout_seconds=5)

    updated = service.update_worktree_config("repo", config)

    assert updated.worktree == config
    assert load_repos(paths)[0].worktree == config
    with pytest.raises(RepoNotFoundError):
        service.update_worktree_config("nope", config)


async def test_suggest_links_lists_ignored_env_and_local_files(
    service: RepoService, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text(
        ".env*\n!.env.example\n*.local\n*.local.*\nnode_modules/\n*.log\n", encoding="utf-8"
    )
    commit_file(repo, ".env.example")
    files = [
        ".env",
        ".env.production",
        "web/.env.local",
        "settings.local.json",
        "app.local",
        "node_modules/pkg/.env",
        "dist/.env",
        "debug.log",
    ]
    for name in files:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("x", encoding="utf-8")
    (repo / ".env.d").mkdir()
    (repo / ".env.d" / "a").write_text("x", encoding="utf-8")
    await service.register(repo)

    suggestions = await service.suggest_links("repo")

    assert suggestions == [
        ".env",
        ".env.production",
        "app.local",
        "settings.local.json",
        "web/.env.local",
    ]


async def test_suggest_links_needs_the_repo_folder(service: RepoService, tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    await service.register(repo)
    shutil.rmtree(repo)

    with pytest.raises(RepoFolderMissingError, match="the folder of repo 'repo' no longer exists"):
        await service.suggest_links("repo")


async def test_unregister_deletes_only_the_config_file(
    service: RepoService, paths: AppPaths, tmp_path: Path
) -> None:
    kept = await service.register(init_repo(tmp_path / "kept"))
    repo = init_repo(tmp_path / "repo")
    await service.register(repo)

    service.unregister("repo")

    assert service.list_repos() == [kept]
    assert not (paths.repos_dir / "repo.toml").exists()
    assert (repo / "README.md").is_file()
    with pytest.raises(RepoNotFoundError):
        service.unregister("repo")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".env", True),
        ("a/b/.env.test", True),
        ("x.local", True),
        ("config.local.yaml", True),
        ("environment", False),
        ("local", False),
        (".venv/.env", False),
        ("venv/x.local", False),
        ("build/.env", False),
        (".git/x.local", False),
        ("node_modules/", False),
        (".env.d/", False),
    ],
)
def test_link_candidate_rules(path: str, expected: bool) -> None:
    assert is_link_candidate(path) is expected
