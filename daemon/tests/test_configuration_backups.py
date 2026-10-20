"""B97 rule 2: a backup before every change, and undoing a copy from it."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.configuration.backups import MANIFEST, Backups, remove
from nestd.configuration.errors import ChangedOnDiskError, UnknownItemError
from nestd.configuration.files import file_version, read_text, tree_version, write_text
from tests.fakes import FakeClock


@pytest.fixture
def backups(tmp_path: Path, clock: FakeClock) -> Backups:
    return Backups(tmp_path / "backups", clock, keep=3)


def test_a_backup_mirrors_the_absolute_path(backups: Backups, tmp_path: Path) -> None:
    file = tmp_path / "claude" / "CLAUDE.md"
    write_text(file, "mine\n")

    backup = backups.start("file")
    backup.save(file)
    backup.save(file)

    assert backup.id.endswith("-file")
    mirror = backup.folder / file.relative_to("/")
    assert mirror.read_text(encoding="utf-8") == "mine\n"
    manifest = json.loads((backup.folder / MANIFEST).read_text(encoding="utf-8"))
    assert manifest["op"] == "file"
    assert [entry["path"] for entry in manifest["entries"]] == [str(file)]


def test_folders_and_links_are_copied_as_they_are(backups: Backups, tmp_path: Path) -> None:
    folder = tmp_path / "skills" / "one"
    write_text(folder / "SKILL.md", "x")
    (folder / "link").symlink_to("../elsewhere")
    link = tmp_path / "codex-link"
    link.symlink_to(tmp_path / "skills")

    backup = backups.start("skills")
    backup.save(folder)
    backup.save(link)
    backup.save(tmp_path / "missing")

    assert (backup.folder / folder.relative_to("/") / "SKILL.md").is_file()
    assert (backup.folder / folder.relative_to("/") / "link").readlink() == Path("../elsewhere")
    assert (backup.folder / link.relative_to("/")).readlink() == tmp_path / "skills"


def test_names_are_unique_and_only_the_newest_are_kept(backups: Backups, clock: FakeClock) -> None:
    first = backups.start("a")
    second = backups.start("a")
    assert second.id == f"{first.id}-2"
    for _ in range(3):
        clock.advance(timedelta(seconds=1))
        backups.start("b")

    assert not first.folder.exists()
    assert not second.folder.exists()


def test_undo_restores_only_what_was_backed_up(backups: Backups, tmp_path: Path) -> None:
    shared = tmp_path / "AGENTS.md"
    claude = tmp_path / "CLAUDE.md"
    created = tmp_path / "skills" / "new"
    untouched = tmp_path / "other.md"
    write_text(shared, "old shared\n")
    write_text(claude, "claude's\n")
    write_text(untouched, "keep\n")
    json_file = tmp_path / "claude.json"
    write_text(json_file, "{}")

    backup = backups.start("copy-claude")
    for path in (shared, claude, created):
        backup.save(path)
    backup.save(json_file, restore=False)
    write_text(shared, "claude's\n")
    write_text(claude, "@AGENTS.md\n")
    write_text(created / "SKILL.md", "x")
    write_text(json_file, '{"mcpServers": {}}')
    backup.finish_undoable({"codex": ["context7"]})

    loaded = backups.load(backup.id)
    assert loaded.added_servers == {"codex": ["context7"]}
    loaded.restore()

    assert read_text(shared) == "old shared\n"
    assert read_text(claude) == "claude's\n"
    assert not created.exists()
    assert read_text(untouched) == "keep\n"
    assert read_text(json_file) == '{"mcpServers": {}}'
    with pytest.raises(ChangedOnDiskError, match="undone already"):
        backups.load(backup.id).restore()


def test_undo_refuses_when_a_path_changed_since(backups: Backups, tmp_path: Path) -> None:
    shared = tmp_path / "AGENTS.md"
    claude = tmp_path / "CLAUDE.md"
    write_text(shared, "old\n")
    write_text(claude, "mine\n")
    backup = backups.start("copy-claude")
    backup.save(claude)
    backup.save(shared)
    write_text(shared, "new\n")
    write_text(claude, "@x\n")
    backup.finish_undoable({})
    write_text(shared, "edited after\n")

    with pytest.raises(ChangedOnDiskError, match=r"AGENTS\.md changed") as raised:
        backups.load(backup.id).restore()

    assert raised.value.current_version == tree_version(shared)
    assert raised.value.payload()["current_version"] == tree_version(shared)
    assert read_text(claude) == "@x\n"


def test_unknown_or_plain_backups_cannot_be_undone(backups: Backups) -> None:
    plain = backups.start("file")
    with pytest.raises(UnknownItemError):
        backups.load(plain.id).restore()
    for name in ("../etc", "nothing", "20260101T000000000000Z-gone"):
        with pytest.raises(UnknownItemError):
            backups.load(name)


def test_files_helpers(tmp_path: Path) -> None:
    file = tmp_path / "deep" / "x.md"
    assert file_version(file) is None
    assert read_text(file) == ""
    assert tree_version(file) is None

    version = write_text(file, "hello")
    file.chmod(0o600)
    assert write_text(file, "again") == file_version(file)
    assert version != file_version(file)
    assert file.stat().st_mode & 0o777 == 0o600
    remove(tmp_path / "missing")
    remove(tmp_path / "deep")
    assert not file.exists()


def test_a_failed_write_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_self: Path, _target: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        write_text(tmp_path / "x.md", "text")
    assert list(tmp_path.iterdir()) == []
