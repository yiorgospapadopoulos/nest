from collections.abc import Sequence
from pathlib import Path

import pytest

from harness.gitops.runner import GitError
from harness.review import head
from harness.review.diff_parser import parse_name_status, parse_patch
from harness.review.diffs import session_diff
from harness.review.models import ReviewCommit, ReviewHead
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


async def test_planted_filters_textconv_and_fsmonitor_never_run_for_a_diff(
    repo: Path, tmp_path: Path
) -> None:
    """D050: the diff runs with the user's credentials after every turn and on approval."""
    marker = tmp_path / "ran"
    program = f"sh -c 'echo ran >> {marker}; cat'"
    commit_file(repo, "notes.txt", "one\n")
    base = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "config", "filter.Evil.Driver.clean", program)
    git(repo, "config", "filter.Evil.Driver.smudge", program)
    git(repo, "config", "filter.Evil.Driver.required", "true")
    git(repo, "config", "diff.evil.textconv", program)
    git(repo, "config", "core.fsmonitor", program)
    (repo / ".gitattributes").write_text("*.txt filter=Evil.Driver diff=evil\n", encoding="utf-8")
    (repo / "notes.txt").write_text("one\ntwo\n", encoding="utf-8")

    diff = await session_diff(repo, base)

    assert not marker.exists()
    notes = next(f for f in diff.files if f.path == "notes.txt")
    assert (notes.additions, notes.deletions) == (1, 0)


async def test_a_filter_driver_that_cannot_be_switched_off_stops_the_diff(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "config", "filter.a=b.clean", "evil")

    with pytest.raises(GitError, match="cannot be switched off"):
        await session_diff(repo, base)


async def test_a_file_replaced_by_a_symlink_is_one_change(repo: Path) -> None:
    """BUG-01: git lists a typechange once but patches it as a deletion and an addition."""
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "keep.txt").unlink()
    (repo / "keep.txt").symlink_to("old.txt")
    (repo / "gone.txt").write_text("bye\nfor now\n", encoding="utf-8")

    diff = await session_diff(repo, base)

    gone, keep = diff.files
    assert (keep.path, keep.status, keep.additions, keep.deletions) == (
        "keep.txt",
        "modified",
        1,
        3,
    )
    assert [line.text for hunk in keep.hunks for line in hunk.lines] == ["a", "b", "c", "old.txt"]
    assert (gone.path, gone.additions, gone.deletions) == ("gone.txt", 1, 0)


async def test_an_untracked_nested_repository_is_listed_as_a_folder(repo: Path) -> None:
    """BUG-01: an agent may clone a repository into the tree."""
    base = git(repo, "rev-parse", "HEAD").strip()
    init_repo(repo / "lib")
    (repo / "fresh.txt").write_text("one\n", encoding="utf-8")

    diff = await session_diff(repo, base)

    fresh, nested = diff.files
    assert (nested.path, nested.status, nested.additions, nested.hunks) == ("lib/", "added", 0, [])
    # BUG-65: shown as a repository of its own, which harness will not commit.
    assert (nested.nested_repository, fresh.nested_repository) == (True, False)
    assert (fresh.path, fresh.additions) == ("fresh.txt", 1)


async def test_unusual_paths_get_their_own_changes(repo: Path) -> None:
    """Patch sections are matched to files by path, also where git quotes the path."""
    tabbed, cafe, spaced = "tab\there.txt", 'caf\u00e9 "q".txt', "x b/y.txt"
    (repo / "x b").mkdir()
    rows = "".join(f"{n}\n" for n in range(10))
    for name in (tabbed, cafe, spaced):
        (repo / name).write_text(rows, encoding="utf-8")
        git(repo, "add", name)
    git(repo, "commit", "-q", "-m", "unusual names")
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / spaced).write_text(f"{rows}more\n", encoding="utf-8")
    (repo / cafe).write_text(rows[2:], encoding="utf-8")
    (repo / "\u00fcber").mkdir()
    moved = "\u00fcber/tab\there.txt"
    git(repo, "mv", tabbed, moved)
    (repo / moved).write_text(f"{rows}more\n", encoding="utf-8")

    diff = await session_diff(repo, base)

    by_path = {f.path: f for f in diff.files}
    assert set(by_path) == {spaced, cafe, moved}
    assert (by_path[spaced].additions, by_path[spaced].deletions) == (1, 0)
    assert (by_path[cafe].additions, by_path[cafe].deletions) == (0, 1)
    renamed = by_path[moved]
    assert (renamed.status, renamed.old_path) == ("renamed", tabbed)
    assert (renamed.additions, renamed.deletions) == (1, 0)


@pytest.mark.parametrize(
    "settings",
    [
        [("diff.noprefix", "true")],
        [("diff.mnemonicPrefix", "true")],
        [("diff.srcPrefix", "x/"), ("diff.dstPrefix", "y/")],
    ],
)
async def test_diff_prefix_settings_never_blank_a_change(
    repo: Path, settings: list[tuple[str, str]]
) -> None:
    """BUG-52: the agent may set these with an allowed `git config`; the user may have them."""
    base = git(repo, "rev-parse", "HEAD").strip()
    for key, value in settings:
        git(repo, "config", key, value)
    (repo / "keep.txt").write_text("a\nB\nc\n", encoding="utf-8")
    spaced = repo / "with space \u00e9.txt"
    spaced.write_text("one\n", encoding="utf-8")
    git(repo, "add", spaced.name)
    git(repo, "commit", "-q", "-m", "quoted name")
    spaced.write_text("one\ntwo\n", encoding="utf-8")

    diff = await session_diff(repo, base)

    by_path = {f.path: f for f in diff.files}
    assert (by_path["keep.txt"].additions, by_path["keep.txt"].deletions) == (1, 1)
    assert len(by_path["keep.txt"].hunks) == 1
    assert (by_path[spaced.name].additions, len(by_path[spaced.name].hunks)) == (2, 1)


async def test_the_diff_names_head_and_its_branch(repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD").strip()

    diff = await session_diff(repo, head)
    git(repo, "checkout", "-q", "--detach")
    detached = await session_diff(repo, head)

    assert diff.head == ReviewHead(commit=head, branch="main")
    assert detached.head == ReviewHead(commit=head, branch=None)


async def test_a_repository_without_commits_has_no_head(tmp_path: Path) -> None:
    repo = tmp_path / "fresh"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")

    diff = await session_diff(repo, None)

    assert diff.head == ReviewHead(commit=None, branch="main")
    assert diff.commits == []


async def test_commits_the_base_and_the_published_work_do_not_hold_are_listed(repo: Path) -> None:
    """SEC-02: a commit made behind the review's back is shown, whatever made it."""
    base = git(repo, "rev-parse", "HEAD").strip()
    published = commit_file(repo, "approved.txt")
    hidden = commit_file(repo, "hidden.txt")
    second = commit_file(repo, "also hidden.txt")

    diff = await session_diff(repo, base, published)
    nothing_published = await session_diff(repo, base)
    without_base = await session_diff(repo, None)

    assert diff.commits == [
        ReviewCommit(sha=second, subject="add also hidden.txt"),
        ReviewCommit(sha=hidden, subject="add hidden.txt"),
    ]
    assert [c.sha for c in nothing_published.commits] == [second, hidden, published]
    assert len(without_base.commits) == 7
    assert without_base.commits[-1] == ReviewCommit(
        sha=git(repo, "rev-list", "--max-parents=0", "HEAD").strip(), subject="init"
    )
    assert (await session_diff(repo, base, second)).commits == []


async def test_replace_refs_hide_neither_changes_nor_commits(repo: Path) -> None:
    """`git replace` (allowed by the git guard) could make the base look like the work, or
    the work's commits look like the base's; the daemon's git reads the real objects.
    """
    base = git(repo, "rev-parse", "HEAD").strip()
    hidden = commit_file(repo, "keep.txt", "a\nB\nc\n")
    git(repo, "replace", "--graft", base, hidden)
    (repo / "notes.txt").write_text("new\n", encoding="utf-8")
    original = git(repo, "rev-parse", f"{base}:old.txt").strip()
    planted = git(repo, "hash-object", "-w", "notes.txt").strip()
    git(repo, "replace", original, planted)
    (repo / "old.txt").write_text("new\n", encoding="utf-8")

    diff = await session_diff(repo, base)

    assert [c.sha for c in diff.commits] == [hidden]
    by_path = {f.path: f for f in diff.files}
    assert by_path["old.txt"].deletions == 20
    assert by_path["keep.txt"].additions == 1


async def test_reading_head_reports_unexpected_git_failures(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing(args: Sequence[str], cwd: Path) -> str:
        raise GitError(args, 128, "fatal: bad object HEAD")

    monkeypatch.setattr(head, "run_git", failing)

    with pytest.raises(GitError, match="bad object"):
        await session_diff(repo, git(repo, "rev-parse", "HEAD").strip())
