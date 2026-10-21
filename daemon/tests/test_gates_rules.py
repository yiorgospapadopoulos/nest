import pytest

from nestd.design.icon import ICON_OUTPUTS
from nestd.design.outputs import CSS_OUTPUT, MASCOTS_SWIFT_OUTPUT, MASCOTS_TS_OUTPUT, SWIFT_OUTPUT
from nestd.gates.rules import ALL_PARTS, classify, select


@pytest.mark.parametrize(
    ("path", "parts"),
    [
        ("daemon/src/nestd/cli.py", {"daemon"}),
        ("daemon/pyproject.toml", {"daemon"}),
        ("daemon/tests/test_cli.py", {"daemon"}),
        ("web/src/App.tsx", {"web"}),
        ("web/package-lock.json", {"web"}),
        ("web/README.md", {"web"}),
        ("apple/Sources/NestKit/Store.swift", {"apple"}),
        ("apple/scripts/coverage.sh", {"apple"}),
        ("apple/support/AppIcon.icns", {"apple"}),
    ],
)
def test_a_file_inside_a_part_runs_that_part(path: str, parts: set[str]) -> None:
    assert classify(path).parts == parts


@pytest.mark.parametrize("path", ["README.md", "LICENSE", "docs/decisions.md", "docs/a/b.md"])
def test_docs_run_no_gate(path: str) -> None:
    choice = classify(path)
    assert choice.parts == set()
    assert choice.reason == "documentation"


@pytest.mark.parametrize(
    "path",
    ["design/tokens.toml", "design/mascots.toml", "daemon/src/nestd/design/css.py"],
)
def test_the_design_source_and_its_generator_run_every_part(path: str) -> None:
    assert classify(path).parts == set(ALL_PARTS)


@pytest.mark.parametrize(
    ("path", "part"),
    [
        (str(CSS_OUTPUT), "web"),
        (str(MASCOTS_TS_OUTPUT), "web"),
        (str(SWIFT_OUTPUT), "apple"),
        (str(MASCOTS_SWIFT_OUTPUT), "apple"),
        *[(str(path), path.parts[0]) for path in ICON_OUTPUTS],
    ],
)
def test_a_generated_file_also_runs_the_daemon_that_checks_it(path: str, part: str) -> None:
    choice = classify(path)
    assert choice.parts == {part, "daemon"}
    assert "generated" in choice.reason


@pytest.mark.parametrize(
    "path",
    [
        "Makefile",
        ".github/workflows/check.yml",
        ".gitignore",
        "scripts/new.sh",
        "daemonx/file.py",
        "webapp/index.html",
        "daemon",
    ],
)
def test_shared_and_unknown_paths_run_every_part(path: str) -> None:
    choice = classify(path)
    assert choice.parts == set(ALL_PARTS)
    assert choice.reason == "shared or unmapped file"


def test_selecting_merges_the_parts_in_gate_order() -> None:
    selection = select(["apple/a.swift", "README.md", "daemon/a.py", "apple/b.swift"])
    assert selection.parts == ("daemon", "apple")
    assert [choice.path for choice in selection.because("apple")] == [
        "apple/a.swift",
        "apple/b.swift",
    ]
    assert selection.because("web") == []


def test_a_rename_across_parts_runs_both_sides() -> None:
    assert select(["daemon/old.py", "web/new.ts"]).parts == ("daemon", "web")


def test_one_unknown_path_runs_everything() -> None:
    assert select(["web/a.ts", "tools/x"]).parts == ALL_PARTS


def test_no_changes_run_nothing() -> None:
    assert select([]).parts == ()
