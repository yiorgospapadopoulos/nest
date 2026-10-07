"""Register existing checkouts and manage their per-repo config."""

import asyncio
import re
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from harness.config.loader import delete_repo, load_repos, save_repo
from harness.config.models import RepoConfig, WorktreeConfig
from harness.errors import ConflictError, InvalidInputError, NotFoundError
from harness.gitops.runner import GitError, run_git
from harness.paths import AppPaths

FALLBACK_BRANCH = "main"
LINK_PATTERNS = (".env", ".env.*", "*.local", "*.local.*")
SKIPPED_DIRS = frozenset({"node_modules", ".venv", "venv", "dist", "build", ".git"})


class RepoNotFoundError(NotFoundError):
    pass


class RepoExistsError(ConflictError):
    pass


class InvalidRepoError(InvalidInputError):
    pass


class RepoFolderMissingError(ConflictError):
    pass


class RepoInUseError(ConflictError):
    pass


def require_folder(repo: RepoConfig) -> None:
    """Git, and so worktrees and sessions, need the repo's folder on disk."""
    if not repo.path.is_dir():
        msg = f"the folder of repo {repo.name!r} no longer exists: {repo.path}"
        raise RepoFolderMissingError(msg)


def is_link_candidate(path: str) -> bool:
    """Gitignored files worth symlinking into worktrees, such as `.env` and `*.local`."""
    if path.endswith("/"):
        return False
    parts = PurePosixPath(path).parts
    if SKIPPED_DIRS.intersection(parts[:-1]):
        return False
    return any(fnmatchcase(parts[-1], pattern) for pattern in LINK_PATTERNS)


class RepoService:
    def __init__(self, paths: AppPaths) -> None:
        self._paths = paths

    def list_repos(self) -> list[RepoConfig]:
        return load_repos(self._paths)

    def get(self, name: str) -> RepoConfig:
        for repo in self.list_repos():
            if repo.name == name:
                return repo
        msg = f"unknown repo {name!r}"
        raise RepoNotFoundError(msg)

    async def register(self, path: Path, name: str | None = None) -> RepoConfig:
        root = await _work_tree_root(path)
        try:
            repo = RepoConfig(
                name=name or _slug(root.name),
                path=root,
                default_branch=await _default_branch(root),
            )
        except ValidationError as error:
            msg = f"invalid repo name {name!r}"
            raise InvalidRepoError(msg) from error
        for existing in self.list_repos():
            if existing.name == repo.name:
                msg = f"repo {repo.name!r} already exists"
                raise RepoExistsError(msg)
            if existing.path == root:
                msg = f"{root} is already registered as {existing.name!r}"
                raise RepoExistsError(msg)
        save_repo(self._paths, repo)
        return repo

    def update_worktree_config(self, name: str, config: WorktreeConfig) -> RepoConfig:
        repo = self.get(name).model_copy(update={"worktree": config})
        save_repo(self._paths, repo)
        return repo

    def unregister(self, name: str) -> None:
        """Delete the repo's config; its folder is never touched."""
        delete_repo(self._paths, self.get(name).name)

    async def suggest_links(self, name: str) -> list[str]:
        repo = self.get(name)
        require_folder(repo)
        # --directory lists wholly ignored directories (node_modules/) as one entry.
        output = await run_git(
            ["ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"],
            repo.path,
        )
        return sorted(entry for entry in output.split("\0") if entry and is_link_candidate(entry))


async def _work_tree_root(path: Path) -> Path:
    """The canonical path of `path`, which must be the root of a git work tree."""
    if not path.is_absolute():
        msg = f"{path} is not an absolute path"
        raise InvalidRepoError(msg)
    if not await asyncio.to_thread(path.is_dir):
        msg = f"{path} is not a directory"
        raise InvalidRepoError(msg)
    try:
        output = await run_git(["rev-parse", "--show-toplevel", "--show-prefix"], path)
    except GitError as error:
        msg = f"{path} is not a git repository"
        raise InvalidRepoError(msg) from error
    toplevel, prefix = output.split("\n")[:2]
    if prefix:
        msg = f"{path} is not the root of a git work tree (the root is {toplevel})"
        raise InvalidRepoError(msg)
    return Path(toplevel)


async def _default_branch(root: Path) -> str:
    for args in (
        ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
    ):
        try:
            ref = (await run_git(args, root)).strip()
        except GitError:
            continue
        return ref.removeprefix("origin/")
    return FALLBACK_BRANCH


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).lstrip("._-") or "repo"
