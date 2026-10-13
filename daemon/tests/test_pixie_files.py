from datetime import date
from pathlib import Path

import pytest

from harness.pixies.errors import InvalidFileNameError, PixieNotFoundError, StaleFileError
from harness.pixies.files import MEMORY_BUDGET, PixieFiles

TODAY = date(2026, 10, 13)


@pytest.fixture
def files(tmp_path: Path) -> PixieFiles:
    files = PixieFiles(tmp_path / "pixies")
    files.create("p1", "You test things.")
    return files


def test_create_lays_out_the_folder(files: PixieFiles, tmp_path: Path) -> None:
    root = tmp_path / "pixies" / "p1"

    assert (root / "SOUL.md").read_text() == "You test things.\n"
    assert (root / "MEMORY.md").read_text() == "# Memory\n"
    assert (root / "notes").is_dir()
    assert (root / "archive").is_dir()
    assert files.workdir("p1") == root / "workdir"
    assert files.workdir("p1").is_dir()


def test_writes_need_the_hash_that_was_read(files: PixieFiles) -> None:
    soul = files.read("p1", "soul")
    saved = files.write("p1", "soul", "You review.", soul.hash)

    with pytest.raises(StaleFileError) as stale:
        files.write("p1", "soul", "Lost update", soul.hash)

    assert saved.text == "You review.\n"
    assert files.read("p1", "soul") == saved
    assert stale.value.payload()["code"] == "stale_file"
    assert stale.value.payload()["hash"] == saved.hash
    assert stale.value.payload()["text"] == "You review.\n"


def test_notes_are_created_without_a_hash_and_listed(files: PixieFiles) -> None:
    created = files.write("p1", "notes/release-steps", "1. tag", None)

    with pytest.raises(StaleFileError):
        files.write("p1", "notes/release-steps", "again", None)

    assert files.notes("p1") == ["release-steps"]
    assert files.read("p1", "notes/release-steps") == created


def test_a_write_with_a_hash_to_a_missing_file_is_stale(files: PixieFiles) -> None:
    with pytest.raises(StaleFileError) as stale:
        files.write("p1", "notes/new-note", "text", "some-hash")

    assert stale.value.payload()["text"] == ""
    assert not (files.workdir("p1").parent / "notes" / "new-note.md").exists()


@pytest.mark.parametrize(
    "name",
    ["notes/../SOUL", "notes/a/b", "notes/.hidden", "notes/", "notes/" + "a" * 65, "SOUL.md", "x"],
)
def test_bad_names_are_refused(files: PixieFiles, name: str) -> None:
    with pytest.raises(InvalidFileNameError):
        files.read("p1", name)
    with pytest.raises(InvalidFileNameError):
        files.write("p1", name, "x", None)


def test_unknown_pixie_and_missing_note(files: PixieFiles) -> None:
    with pytest.raises(PixieNotFoundError):
        files.read("nope", "soul")
    with pytest.raises(PixieNotFoundError):
        files.read("p1", "notes/missing")


def test_memory_is_readable_and_writable_by_name(files: PixieFiles) -> None:
    memory = files.read("p1", "memory")
    written = files.write("p1", "memory", "# Memory\n- 2026-10-13: edited\n", memory.hash)

    assert written.text == "# Memory\n- 2026-10-13: edited\n"


def test_facts_are_dated_redacted_and_forgotten(files: PixieFiles) -> None:
    files.add_fact("p1", "prefers squash merges", TODAY)
    files.add_fact("p1", "token ghp_abcdefghijklmnopqrstuvwxyz0123 for CI", TODAY)

    removed = files.forget("p1", "SQUASH")
    memory = files.read("p1", "memory").text

    assert removed == 1
    assert memory == "# Memory\n- 2026-10-13: token [redacted] for CI\n"


def test_forget_leaves_text_that_is_not_a_fact_alone(files: PixieFiles) -> None:
    files.add_fact("p1", "keep me", TODAY)

    assert files.forget("p1", "Memory") == 0
    assert files.read("p1", "memory").text == "# Memory\n- 2026-10-13: keep me\n"


def test_facts_collapse_whitespace_and_newlines(files: PixieFiles) -> None:
    saved = files.add_fact("p1", "one\n  two\tthree", TODAY)

    assert saved.text == "# Memory\n- 2026-10-13: one two three\n"


def test_a_full_memory_moves_old_facts_to_the_archive(files: PixieFiles, tmp_path: Path) -> None:
    fact = "x" * 200
    for _ in range(MEMORY_BUDGET // 200 + 5):
        files.add_fact("p1", fact, TODAY)

    memory = files.read("p1", "memory").text
    archive = (tmp_path / "pixies" / "p1" / "archive" / "2026-10.md").read_text()

    assert len(memory.encode()) <= MEMORY_BUDGET
    assert memory.startswith("# Memory\n- 2026-10-13: ")
    assert archive.count("- 2026-10-13: ") >= 5


def test_an_oversized_fact_is_archived_even_alone(files: PixieFiles, tmp_path: Path) -> None:
    files.add_fact("p1", "y" * MEMORY_BUDGET, TODAY)

    memory = files.read("p1", "memory").text
    archive = (tmp_path / "pixies" / "p1" / "archive" / "2026-10.md").read_text()

    assert memory == "# Memory\n"
    assert archive.startswith("- 2026-10-13: yyy")


def test_archiving_stops_when_no_fact_lines_are_left(files: PixieFiles, tmp_path: Path) -> None:
    memory = files.read("p1", "memory")
    files.write("p1", "memory", "#" * (MEMORY_BUDGET + 1), memory.hash)

    saved = files.add_fact("p1", "tiny", TODAY)
    archive = (tmp_path / "pixies" / "p1" / "archive" / "2026-10.md").read_text()

    assert saved.text == "#" * (MEMORY_BUDGET + 1) + "\n"
    assert archive == "- 2026-10-13: tiny\n"


def test_search_looks_through_memory_notes_and_archive(files: PixieFiles, tmp_path: Path) -> None:
    files.add_fact("p1", "Uses pnpm", TODAY)
    files.write("p1", "notes/tooling", "pnpm workspaces\nvite", None)
    (tmp_path / "pixies" / "p1" / "archive" / "2026-09.md").write_text("- old: PNPM v8\n")

    hits = files.search("p1", "pnpm")

    assert [(h.file, h.line) for h in hits] == [
        ("MEMORY.md", "- 2026-10-13: Uses pnpm"),
        ("notes/tooling.md", "pnpm workspaces"),
        ("archive/2026-09.md", "- old: PNPM v8"),
    ]


def test_search_of_an_unknown_pixie_is_refused(files: PixieFiles) -> None:
    with pytest.raises(PixieNotFoundError):
        files.search("nope", "pnpm")


def test_remove_deletes_the_folder(files: PixieFiles, tmp_path: Path) -> None:
    files.remove("p1")
    files.remove("p1")

    assert not (tmp_path / "pixies" / "p1").exists()
