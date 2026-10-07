import shutil
from pathlib import Path

import pytest

from harness.config.loader import load_repos
from harness.config.models import RepoConfig, WorktreeConfig
from harness.paths import AppPaths
from harness.repos.service import (
    InvalidRepoError,
    RepoExistsError,
    RepoFolderMissingError,
    RepoNotFoundError,
    RepoService,
    is_link_candidate,
)
from tests.git_support import commit_file, git, init_repo


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    result.ensure()
    return result


@pytest.fixture
def service(paths: AppPaths) -> RepoService:
    return RepoService(paths)


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


async def test_register_rejects_missing_dirs_non_repos_and_subdirectories(
    service: RepoService, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "sub").mkdir()
    plain = tmp_path / "plain"
    plain.mkdir()

    with pytest.raises(InvalidRepoError, match="not a directory"):
        await service.register(tmp_path / "missing")
    with pytest.raises(InvalidRepoError, match="not a git repository"):
        await service.register(plain)
    with pytest.raises(InvalidRepoError, match="not the root of a git work tree"):
        await service.register(repo / "sub")
    with pytest.raises(InvalidRepoError, match="not an absolute path"):
        await service.register(Path("relative/repo"))


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
