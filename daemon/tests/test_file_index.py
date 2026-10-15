import logging
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.gitops.runner import GitError
from nestd.sessions.files import FileIndex
from tests.fakes import FakeClock
from tests.git_support import init_repo


def write(root: Path, *names: str) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name, encoding="utf-8")


async def test_tracked_and_untracked_files_but_not_ignored_ones(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = init_repo(tmp_path / "repo")
    write(repo, ".gitignore")
    (repo / ".gitignore").write_text("secret.env\nbuild/\n", encoding="utf-8")
    write(repo, "src/new_module.py", "secret.env", "build/out.js")

    files = await FileIndex(clock).search(repo, "")

    assert "src/new_module.py" in files
    assert ".gitignore" in files
    assert "secret.env" not in files
    assert "build/out.js" not in files


async def test_matches_rank_by_name_then_path_then_letters_in_order(
    tmp_path: Path, clock: FakeClock
) -> None:
    listing = "\0".join(
        [
            "docs/app-guide.md",
            "src/app.py",
            "src/apps/config.py",
            "web/src/App.tsx",
            "lib/my_app.py",
            "a/p/p/x.txt",
            "readme.md",
        ]
    )

    async def git(args: Sequence[str], cwd: Path) -> str:
        return listing + "\0"

    index = FileIndex(clock, git)

    assert await index.search(tmp_path, "app") == [
        "src/app.py",
        "web/src/App.tsx",
        "docs/app-guide.md",
        "lib/my_app.py",
        "src/apps/config.py",
        "a/p/p/x.txt",
    ]
    assert await index.search(tmp_path, " APP.T ") == ["web/src/App.tsx", "a/p/p/x.txt"]
    assert await index.search(tmp_path, "zzz") == []
    assert await index.search(tmp_path, "", limit=2) == ["readme.md", "src/app.py"]


async def test_listings_are_reused_for_a_few_seconds(tmp_path: Path, clock: FakeClock) -> None:
    calls: list[Path] = []
    files = ["one.py"]

    async def git(args: Sequence[str], cwd: Path) -> str:
        calls.append(cwd)
        return "\0".join(files)

    index = FileIndex(clock, git, ttl=timedelta(seconds=10))

    first = await index.search(tmp_path, "")
    files.append("two.py")
    cached = await index.search(tmp_path, "")
    clock.advance(timedelta(seconds=11))
    fresh = await index.search(tmp_path, "")

    assert first == cached == ["one.py"]
    assert fresh == ["one.py", "two.py"]
    assert len(calls) == 2


async def test_a_git_failure_gives_no_suggestions(
    tmp_path: Path, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    write(tmp_path, "notes.md")

    async def git(args: Sequence[str], cwd: Path) -> str:
        raise GitError(args, 128, "not a git repository")

    with caplog.at_level(logging.WARNING):
        files = await FileIndex(clock, git).search(tmp_path, "x")

    assert files == []
    assert "listing the files" in caplog.text


async def test_a_folder_outside_git_is_walked_without_hidden_and_build_folders(
    tmp_path: Path, clock: FakeClock
) -> None:
    write(
        tmp_path,
        "notes.md",
        ".env",
        "docs/plan.md",
        ".git/config",
        ".cache/x.md",
        "node_modules/pkg/index.js",
        ".venv/lib/site.py",
        "venv/lib/site.py",
        "__pycache__/a.pyc",
        "build/out.js",
        "dist/app.js",
        "target/debug/app",
        "DerivedData/x",
        "Pods/x",
        "src/build/skipped.md",
        "src/builder/kept.md",
    )
    (tmp_path / "linked").symlink_to(tmp_path / "docs")

    async def git(args: Sequence[str], cwd: Path) -> str:
        raise AssertionError("git is not used for a plain folder")

    index = FileIndex(clock, git)

    assert sorted(await index.search(tmp_path, "", git=False)) == [
        ".env",
        "docs/plan.md",
        "notes.md",
        "src/builder/kept.md",
    ]
    assert await index.search(tmp_path, "plan", git=False) == ["docs/plan.md"]


async def test_a_walk_stops_after_enough_files_and_is_reused_for_a_few_seconds(
    tmp_path: Path, clock: FakeClock
) -> None:
    write(tmp_path, "a.md", "b.md", "c.md")
    index = FileIndex(clock, max_walked=2, ttl=timedelta(seconds=10))

    first = await index.search(tmp_path, "", git=False)
    write(tmp_path, "d.md")
    cached = await index.search(tmp_path, "", git=False)
    clock.advance(timedelta(seconds=11))
    (tmp_path / "a.md").unlink()
    (tmp_path / "b.md").unlink()
    (tmp_path / "c.md").unlink()
    fresh = await index.search(tmp_path, "", git=False)

    assert len(first) == 2
    assert cached == first
    assert fresh == ["d.md"]


async def test_an_unreadable_folder_walks_to_nothing(tmp_path: Path, clock: FakeClock) -> None:
    assert await FileIndex(clock).search(tmp_path / "gone", "", git=False) == []
