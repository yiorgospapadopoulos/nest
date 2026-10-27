"""Real git repositories in temporary directories, isolated from the user's git config.

`init_repo` and `with_origin` copy a repository made once per test process instead of
running git each time (B111), so every copy in a process shares the same first commit.
"""

import atexit
import itertools
import shutil
import subprocess
import tempfile
from pathlib import Path


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


class _Templates:
    """The first-commit repositories, and their bare origins, by branch name."""

    def __init__(self) -> None:
        self._folder: Path | None = None
        self.repos: dict[str, Path] = {}
        self.origins: dict[str, tuple[Path, str]] = {}
        self._numbers = itertools.count()

    def place(self, name: str) -> Path:
        if self._folder is None:
            self._folder = Path(tempfile.mkdtemp(prefix="nest-git-templates-"))
            atexit.register(shutil.rmtree, self._folder, ignore_errors=True)
        return self._folder / f"{next(self._numbers)}-{name}"


_templates = _Templates()


def init_repo(path: Path, branch: str = "main") -> Path:
    if (path / ".git").exists():
        return _init_repo(path, branch)
    template = _templates.repos.get(branch)
    if template is None:
        template = _init_repo(_templates.place("repo"), branch)
        _templates.repos[branch] = template
    shutil.copytree(template, path, symlinks=True, dirs_exist_ok=True)
    return path


def _init_repo(path: Path, branch: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "init")
    return path


def commit_file(repo: Path, name: str, content: str = "x\n") -> str:
    (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD").strip()


def with_origin(repo: Path, origin: Path, branch: str = "main") -> Path:
    """Give `repo` a bare `origin` holding its branch, like a GitHub remote."""
    template = _origin_template(branch)
    if template is None or _loose_head(repo, branch) != template[1]:
        return _with_origin(repo, origin, branch)
    # `repo` still holds only the template's first commit: the origin's copy has it too,
    # so the push is the tracking ref it would have written.
    shutil.copytree(template[0], origin, symlinks=True)
    git(repo, "remote", "add", "origin", str(origin))
    tracking = repo / ".git" / "refs" / "remotes" / "origin" / branch
    tracking.parent.mkdir(parents=True, exist_ok=True)
    tracking.write_text(f"{template[1]}\n", encoding="utf-8")
    return origin


def _origin_template(branch: str) -> tuple[Path, str] | None:
    """The bare origin of the branch's template repository, made on first use."""
    if branch not in _templates.repos:
        return None
    found = _templates.origins.get(branch)
    if found is None:
        source = init_repo(_templates.place("source"), branch)
        bare = _with_origin(source, _templates.place("origin.git"), branch)
        found = (bare, git(source, "rev-parse", "HEAD").strip())
        _templates.origins[branch] = found
    return found


def _loose_head(repo: Path, branch: str) -> str | None:
    """The branch's commit when it is stored as a loose ref, else None."""
    ref = repo / ".git" / "refs" / "heads" / branch
    return ref.read_text(encoding="utf-8").strip() if ref.is_file() else None


def _with_origin(repo: Path, origin: Path, branch: str) -> Path:
    origin.mkdir(parents=True)
    git(origin, "init", "-q", "--bare", "-b", branch)
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", branch)
    return origin
