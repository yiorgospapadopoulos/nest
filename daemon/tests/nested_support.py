"""Repositories inside the work (submodules, nested clones) with a planted filter (SEC-08)."""

from pathlib import Path

from tests.git_support import git, init_repo


def add_nested_repo(repo: Path, name: str = "lib") -> Path:
    """A repository at `repo/name`, committed into `repo` as a gitlink."""
    nested = init_repo(repo / name)
    git(repo, "-c", "advice.addEmbeddedRepo=false", "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")
    return nested


def plant_filter(nested: Path, marker: Path, driver: str = "evil") -> None:
    """A clean filter in the nested repository's own config that records each run, and an
    edit of the same size, so a `git status` inside it must run the filter to compare.
    """
    git(nested, "config", f"filter.{driver}.clean", f"sh -c 'echo ran >> \"{marker}\"; cat'")
    attributes = nested / ".git" / "info" / "attributes"
    attributes.parent.mkdir(parents=True, exist_ok=True)
    attributes.write_text(f"* filter={driver}\n", encoding="utf-8")
    (nested / "README.md").write_text("HELLO\n", encoding="utf-8")
