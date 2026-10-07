"""Register existing checkouts or plain folders (D041) and manage their per-repo config."""

import asyncio
import re
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from pydantic import JsonValue, ValidationError

from harness.config.loader import delete_repo, load_repos, save_repo
from harness.config.models import RepoConfig, WorktreeConfig
from harness.errors import ConflictError, InvalidInputError, NotFoundError
from harness.events import types
from harness.events.bus import EventBus
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


class NotAGitRepositoryError(ConflictError):
    """A git action asked of a plain folder project (D041)."""

    code = "not_a_git_repository"

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is not a git repository")

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


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
    def __init__(self, paths: AppPaths, bus: EventBus | None = None) -> None:
        self._paths = paths
        self._bus = bus

    def list_repos(self) -> list[RepoConfig]:
        return load_repos(self._paths)

    def get(self, name: str) -> RepoConfig:
        for repo in self.list_repos():
            if repo.name == name:
                return repo
        msg = f"unknown repo {name!r}"
        raise RepoNotFoundError(msg)

    async def current(self, name: str) -> RepoConfig:
        """The repo, after checking whether a plain folder has become a git repository."""
        return await self._detect_git(self.get(name))

    async def list_current(self) -> list[RepoConfig]:
        return [await self._detect_git(repo) for repo in self.list_repos()]

    async def has_git(self, name: str) -> bool:
        """Unknown repos count as git: the git commands that follow report their errors."""
        try:
            return (await self.current(name)).git
        except RepoNotFoundError:
            return True

    async def require_git(self, name: str) -> None:
        if not await self.has_git(name):
            raise NotAGitRepositoryError(name)

    async def register(self, path: Path, name: str | None = None) -> RepoConfig:
        """A git work tree's root, or a folder outside any work tree as a plain folder."""
        root = await _work_tree_root(path)
        plain = root is None
        if root is None:
            root = await asyncio.to_thread(path.resolve)
        try:
            repo = RepoConfig(
                name=name or _slug(root.name),
                path=root,
                git=not plain,
                default_branch=None if plain else await _default_branch(root),
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
        repo = await self.current(name)
        require_folder(repo)
        if not repo.git:
            raise NotAGitRepositoryError(name)
        # --directory lists wholly ignored directories (node_modules/) as one entry.
        output = await run_git(
            ["ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"],
            repo.path,
        )
        return sorted(entry for entry in output.split("\0") if entry and is_link_candidate(entry))

    async def _detect_git(self, repo: RepoConfig) -> RepoConfig:
        """A plain folder whose root is now a git work tree (the user or the agent ran
        `git init`) becomes a git repo: saved and announced. A stat first keeps it cheap.
        """
        if repo.git or not await asyncio.to_thread((repo.path / ".git").exists):
            return repo
        try:
            toplevel = await run_git(["rev-parse", "--show-toplevel"], repo.path)
        except GitError:
            return repo
        if Path(toplevel.strip()) != repo.path:
            return repo
        updated = RepoConfig.model_validate(
            {
                **repo.model_dump(),
                "git": True,
                "default_branch": await _default_branch(repo.path),
            }
        )
        save_repo(self._paths, updated)
        if self._bus is not None:
            await self._bus.publish(
                types.REPO_UPDATED, {"name": updated.name, "repo": updated.model_dump(mode="json")}
            )
        return updated


async def _work_tree_root(path: Path) -> Path | None:
    """The canonical path of `path`, which must be the root of a git work tree; None
    when it is outside any work tree.
    """
    if not path.is_absolute():
        msg = f"{path} is not an absolute path"
        raise InvalidRepoError(msg)
    if not await asyncio.to_thread(path.is_dir):
        msg = f"{path} is not a directory"
        raise InvalidRepoError(msg)
    try:
        output = await run_git(["rev-parse", "--show-toplevel", "--show-prefix"], path)
    except GitError as error:
        if error.not_a_repository:
            return None
        msg = f"{path} cannot be read by git: {error.stderr.strip()}"
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
