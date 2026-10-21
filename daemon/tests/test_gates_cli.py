import dataclasses
import io
from pathlib import Path

import pytest

from nestd.cli import main
from nestd.runtime import default_runtime
from tests.git_support import git


@dataclasses.dataclass
class Result:
    code: int
    out: str
    err: str


def changed(*argv: str) -> Result:
    out, err = io.StringIO(), io.StringIO()
    runtime = dataclasses.replace(default_runtime(), out=out, err=err)
    code = main(["gates", "changed", *argv], runtime)
    return Result(code, out.getvalue(), err.getvalue())


def write(root: Path, relative: str, content: str = "x\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository like Nest's on a feature branch with no changes yet."""
    root = tmp_path / "nest"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    for relative in ("README.md", "daemon/a.py", "web/a.ts", "apple/a.swift", "design/tokens.toml"):
        write(root, relative)
    write(root, ".gitignore", "ignored/\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "init")
    git(root, "switch", "-q", "-c", "feature")
    return root


def commit(root: Path, message: str = "change") -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def test_an_empty_diff_runs_nothing(repo: Path) -> None:
    result = changed("--root", str(repo))
    assert result.code == 0
    assert result.out == "\n"
    assert "no changes since main" in result.err
    assert "daemon: skipped" in result.err


def test_committed_changes_on_the_branch_pick_their_parts(repo: Path) -> None:
    write(repo, "web/a.ts", "changed\n")
    commit(repo)
    result = changed("--root", str(repo))
    assert result.code == 0
    assert result.out == "web\n"
    assert "web: runs (web/a.ts)" in result.err
    assert "daemon: skipped" in result.err
    assert "apple: skipped" in result.err


def test_staged_unstaged_and_untracked_files_count(repo: Path) -> None:
    write(repo, "daemon/a.py", "unstaged\n")
    write(repo, "apple/b.swift")
    git(repo, "add", "apple/b.swift")
    write(repo, "web/new.ts")
    assert changed("--root", str(repo)).out == "daemon web apple\n"


def test_ignored_files_do_not_count(repo: Path) -> None:
    write(repo, "ignored/big.log")
    assert changed("--root", str(repo)).out == "\n"


def test_a_deleted_file_runs_its_part(repo: Path) -> None:
    (repo / "apple/a.swift").unlink()
    commit(repo)
    assert changed("--root", str(repo)).out == "apple\n"


def test_a_rename_across_parts_runs_both(repo: Path) -> None:
    git(repo, "mv", "daemon/a.py", "web/a.py")
    commit(repo)
    assert changed("--root", str(repo)).out == "daemon web\n"


def test_docs_only_run_no_gate_and_say_why(repo: Path) -> None:
    write(repo, "README.md", "more\n")
    write(repo, "docs/decisions.md")
    result = changed("--root", str(repo))
    assert result.out == "\n"
    assert "README.md: documentation, no gate" in result.err


def test_the_design_source_runs_every_part(repo: Path) -> None:
    write(repo, "design/tokens.toml", "changed\n")
    result = changed("--root", str(repo))
    assert result.out == "daemon web apple\n"
    assert "web: runs (design/tokens.toml [design source, feeds every part])" in result.err


def test_changes_on_the_base_after_the_branch_point_do_not_count(repo: Path) -> None:
    write(repo, "web/a.ts", "branch\n")
    commit(repo)
    git(repo, "switch", "-q", "main")
    write(repo, "apple/a.swift", "main moved on\n")
    commit(repo)
    git(repo, "switch", "-q", "feature")
    assert changed("--root", str(repo)).out == "web\n"


def test_another_base_can_be_given(repo: Path) -> None:
    write(repo, "web/a.ts", "one\n")
    commit(repo)
    git(repo, "tag", "checkpoint")
    write(repo, "daemon/a.py", "two\n")
    commit(repo)
    assert changed("--root", str(repo), "--base", "checkpoint").out == "daemon\n"


def test_many_files_in_a_part_are_summarised(repo: Path) -> None:
    for index in range(5):
        write(repo, f"web/f{index}.ts")
    result = changed("--root", str(repo))
    assert "web: runs (web/f0.ts, web/f1.ts, web/f2.ts and 2 more)" in result.err


def test_the_root_defaults_to_the_repository_holding_the_current_folder(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(repo, "apple/a.swift", "changed\n")
    monkeypatch.chdir(repo / "daemon")
    assert changed().out == "apple\n"


def test_an_unknown_base_fails_with_gits_message(repo: Path) -> None:
    result = changed("--root", str(repo), "--base", "no-such-branch")
    assert result.code == 1
    assert result.out == ""
    assert result.err.startswith("nestd: git merge-base no-such-branch HEAD failed: ")


def test_outside_a_repository_it_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = changed()
    assert result.code == 1
    assert "nestd: git rev-parse --show-toplevel failed: " in result.err
