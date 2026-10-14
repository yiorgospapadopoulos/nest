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


async def test_folders_outside_git_have_no_suggestions(
    tmp_path: Path, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    async def git(args: Sequence[str], cwd: Path) -> str:
        raise GitError(args, 128, "not a git repository")

    with caplog.at_level(logging.WARNING):
        files = await FileIndex(clock, git).search(tmp_path, "x")

    assert files == []
    assert "listing the files" in caplog.text
