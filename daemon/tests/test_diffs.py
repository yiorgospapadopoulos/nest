from pathlib import Path

import pytest

from harness.gitops.runner import GitError
from harness.review.diff_parser import parse_name_status, parse_patch
from harness.review.diffs import session_diff
from tests.git_support import commit_file, git, init_repo

PATCH = """\
diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,4 +1,4 @@ def main():
 one
-two
+TWO
 three
\\ No newline at end of file
@@ -10 +10,2 @@
 ten
+eleven
diff --git a/logo.png b/logo.png
new file mode 100644
index 0000000..3333333
Binary files /dev/null and b/logo.png differ
diff --git a/mode.sh b/mode.sh
old mode 100644
new mode 100755
"""


def test_parse_patch_reads_hunks_line_numbers_and_binaries() -> None:
    app, logo, mode = parse_patch(PATCH, max_lines=100)

    assert (app.additions, app.deletions, app.binary, app.truncated) == (2, 1, False, False)
    first, second = app.hunks
    assert (first.old_start, first.old_lines, first.new_start, first.new_lines) == (1, 4, 1, 4)
    assert first.header == "def main():"
    assert [(x.kind, x.text, x.old_line, x.new_line) for x in first.lines] == [
        ("context", "one", 1, 1),
        ("delete", "two", 2, None),
        ("add", "TWO", None, 2),
        ("context", "three", 3, 3),
    ]
    assert (second.old_start, second.old_lines, second.new_start, second.new_lines) == (
        10,
        1,
        10,
        2,
    )
    assert second.header == ""
    assert logo.binary is True
    assert logo.hunks == []
    assert mode.hunks == []
    assert mode.binary is False


def test_parse_patch_truncates_long_files_but_counts_every_line() -> None:
    body = "".join(f"+line {n}\n" for n in range(10))
    patch = (
        f"diff --git a/big b/big\n--- a/big\n+++ b/big\n@@ -1,0 +1,10 @@\n{body}"
        "@@ -20 +30 @@\n-old\n+new\n"
    )

    (big,) = parse_patch(patch, max_lines=3)

    assert big.truncated is True
    assert (big.additions, big.deletions) == (11, 1)
    (hunk,) = big.hunks
    assert [line.text for line in hunk.lines] == ["line 0", "line 1", "line 2"]


def test_parse_patch_of_nothing() -> None:
    assert parse_patch("", max_lines=10) == []


def test_parse_name_status() -> None:
    output = "M\0a.py\0R087\0old name.py\0new name.py\0A\0b.py\0D\0c.py\0T\0d\0C100\0e\0f\0"

    assert parse_name_status(output) == [
        ("modified", None, "a.py"),
        ("renamed", "old name.py", "new name.py"),
        ("added", None, "b.py"),
        ("deleted", None, "c.py"),
        ("modified", None, "d"),
        ("added", "e", "f"),
    ]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = init_repo(tmp_path / "repo")
    commit_file(path, "keep.txt", "a\nb\nc\n")
    commit_file(path, "old.txt", "".join(f"row {n}\n" for n in range(20)))
    commit_file(path, "gone.txt", "bye\n")
    return path


async def test_session_diff_covers_every_kind_of_change(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "keep.txt").write_text("a\nB\nc\n", encoding="utf-8")
    git(repo, "mv", "old.txt", "new.txt")
    (repo / "gone.txt").unlink()
    (repo / "fresh.txt").write_text("one\ntwo\n", encoding="utf-8")
    (repo / "blob.bin").write_bytes(b"\x00\x01binary")
    (repo / "empty.txt").write_text("", encoding="utf-8")
    (repo / "link").symlink_to("keep.txt")
    (repo / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
    (repo / "ignored.log").write_text("noise\n", encoding="utf-8")

    diff = await session_diff(repo, base)

    by_path = {f.path: f for f in diff.files}
    assert [f.path for f in diff.files] == sorted(by_path)
    assert set(by_path) == {
        ".gitignore",
        "blob.bin",
        "empty.txt",
        "fresh.txt",
        "gone.txt",
        "keep.txt",
        "link",
        "new.txt",
    }
    assert (by_path["keep.txt"].status, by_path["keep.txt"].additions) == ("modified", 1)
    assert by_path["keep.txt"].deletions == 1
    renamed = by_path["new.txt"]
    assert (renamed.status, renamed.old_path, renamed.hunks) == ("renamed", "old.txt", [])
    assert (by_path["gone.txt"].status, by_path["gone.txt"].deletions) == ("deleted", 1)
    fresh = by_path["fresh.txt"]
    assert (fresh.status, fresh.additions, fresh.deletions) == ("added", 2, 0)
    (hunk,) = fresh.hunks
    assert (hunk.old_start, hunk.old_lines, hunk.new_start, hunk.new_lines) == (0, 0, 1, 2)
    assert [(x.kind, x.text, x.new_line) for x in hunk.lines] == [
        ("add", "one", 1),
        ("add", "two", 2),
    ]
    assert (by_path["blob.bin"].binary, by_path["blob.bin"].hunks) == (True, [])
    assert (by_path["empty.txt"].additions, by_path["empty.txt"].hunks) == (0, [])
    assert [x.text for x in by_path["link"].hunks[0].lines] == ["keep.txt"]
    assert diff.base == base
    assert (diff.stats.files, diff.stats.additions) == (8, 5)
    assert diff.stats.deletions == 2
    # The index is never touched: the untracked files are still untracked.
    assert "?? fresh.txt" in git(repo, "status", "--porcelain")


async def test_untracked_files_are_truncated_too(repo: Path) -> None:
    (repo / "long.txt").write_text("x\n" * 5000, encoding="utf-8")

    diff = await session_diff(repo, git(repo, "rev-parse", "HEAD").strip())

    (long,) = diff.files
    assert long.truncated is True
    assert long.additions == 5000
    assert sum(len(h.lines) for h in long.hunks) < 5000


async def test_without_a_base_everything_is_new(tmp_path: Path) -> None:
    repo = tmp_path / "fresh"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.txt").write_text("hi\n", encoding="utf-8")

    diff = await session_diff(repo, None)

    assert [(f.path, f.status) for f in diff.files] == [("a.txt", "added")]
    assert diff.base is None


async def test_a_clean_tree_has_no_files(repo: Path) -> None:
    diff = await session_diff(repo, git(repo, "rev-parse", "HEAD").strip())

    assert diff.files == []
    assert (diff.stats.files, diff.stats.additions, diff.stats.deletions) == (0, 0, 0)


async def test_an_unknown_base_is_a_git_error(repo: Path) -> None:
    with pytest.raises(GitError):
        await session_diff(repo, "0" * 40)
