"""Real git repositories in temporary directories, isolated from the user's git config."""

import subprocess
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


def init_repo(path: Path, branch: str = "main") -> Path:
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
    origin.mkdir(parents=True)
    git(origin, "init", "-q", "--bare", "-b", branch)
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", branch)
    return origin
