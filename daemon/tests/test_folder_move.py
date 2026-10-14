"""B43: the config and data folders move from their harness names to Nest's on start."""

import shutil
import socket
import sqlite3
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from nestd.folder_move import (
    BACKUP_SUFFIX,
    MARKER_NAME,
    STAGING_SUFFIX,
    FolderMove,
    FolderMoveError,
    adopt_legacy_database,
    answers,
    legacy_moves,
    move_folder,
)


@pytest.fixture
def root() -> Iterator[Path]:
    """A short folder: the tests bind Unix sockets, whose paths are limited to about 104
    bytes; pytest's tmp_path is often longer."""
    folder = Path(tempfile.mkdtemp(prefix="nx-", dir="/tmp"))
    yield folder
    for path in folder.rglob("*"):
        if not path.is_symlink():
            path.chmod(0o700)
    shutil.rmtree(folder)


def never(_path: Path) -> bool:
    return False


def make_move(root: Path) -> FolderMove:
    return FolderMove(old=root / "harness", new=root / "nest")


def tree(folder: Path) -> dict[str, tuple[str, int]]:
    """What a folder holds: each entry's kind (with a link's target or a file's text) and
    permissions, by relative path."""
    found: dict[str, tuple[str, int]] = {}
    for path in sorted(folder.rglob("*")):
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if path.is_symlink():
            kind = f"link {path.readlink()}"
        elif path.is_dir():
            kind = "dir"
        elif stat.S_ISSOCK(info.st_mode):
            kind = "socket"
        else:
            kind = f"file {path.read_bytes()!r}"
        found[str(path.relative_to(folder))] = (kind, mode)
    return found


def bind_socket(path: Path, *, listen: bool) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    if listen:
        sock.listen(1)
    return sock


def write_wal_database(path: Path) -> sqlite3.Connection:
    """A database whose last rows are still only in its -wal file, as a daemon leaves it."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE chats (title TEXT)")
    conn.executemany("INSERT INTO chats VALUES (?)", [("first",), ("second",)])
    conn.commit()
    return conn


def make_old_data_folder(old: Path) -> None:
    old.mkdir(mode=0o700)
    old.chmod(0o700)
    (old / "attachments" / "s1").mkdir(parents=True)
    (old / "attachments" / "s1" / "photo.png").write_bytes(b"\x89PNG")
    private = old / "pixies" / "ada"
    private.mkdir(parents=True)
    private.chmod(0o700)
    (private / "memory.md").write_text("remember", encoding="utf-8")
    (private / "memory.md").chmod(0o600)
    (old / "pixies" / "current").symlink_to("ada")
    (old / "pixies" / "ada" / "soul.md").symlink_to("memory.md")
    (old / "absolute").symlink_to(old / "attachments" / "s1" / "photo.png")
    (old / "dangling").symlink_to("not-there")


def test_the_default_folders_move_unless_a_variable_names_one(tmp_path: Path) -> None:
    config = FolderMove(tmp_path / ".config" / "harness", tmp_path / ".config" / "nest")
    data = FolderMove(
        tmp_path / "Library" / "Application Support" / "harness",
        tmp_path / "Library" / "Application Support" / "nest",
    )

    assert legacy_moves({}, tmp_path) == [config, data]
    assert legacy_moves({"NEST_CONFIG_DIR": "/c"}, tmp_path) == [data]
    assert legacy_moves({"HARNESS_DATA_DIR": "/d"}, tmp_path) == [config]
    assert legacy_moves({"NEST_DATA_DIR": "/d", "HARNESS_CONFIG_DIR": "/c"}, tmp_path) == []


def test_a_folder_is_copied_then_kept_as_a_backup_with_a_link_at_its_place(root: Path) -> None:
    move = make_move(root)
    make_old_data_folder(move.old)
    stale = bind_socket(move.old / "token.sock", listen=False)
    database = write_wal_database(move.old / "harness.db")
    original = tree(move.old)

    note = move_folder(move, serving=never)

    backup = root / f"harness{BACKUP_SUFFIX}"
    assert note == (
        f"Moved {move.old} to {move.new}; the old folder is kept as {backup}, "
        "with a link to the new one at its place"
    )
    # The backup is the old folder itself, untouched.
    assert tree(backup) == original
    # Every link stays a link with its target, permissions are kept, the socket is left
    # out (the daemon makes a new one) and the database is renamed with its -wal and -shm.
    moved = tree(move.new)
    expected = {
        path.replace("harness.db", "nest.db"): entry
        for path, entry in original.items()
        if path != "token.sock"
    }
    assert {path: entry for path, entry in moved.items() if path != MARKER_NAME} == expected
    assert moved[MARKER_NAME][0] == f"file {(str(move.old) + chr(10)).encode()!r}"
    assert stat.S_IMODE(move.new.stat().st_mode) == 0o700
    assert (move.new / "nest.db-wal").stat().st_size > 0
    assert (move.new / "nest.db-shm").exists()
    # The absolute link still points at the old path, which now leads to the new folder.
    assert (move.new / "absolute").readlink() == move.old / "attachments/s1/photo.png"
    assert move.old.is_symlink()
    assert move.old.readlink() == move.new
    assert (move.new / "absolute").read_bytes() == b"\x89PNG"
    stale.close()
    database.close()
    copied = sqlite3.connect(move.new / "nest.db")
    assert copied.execute("SELECT title FROM chats").fetchall() == [("first",), ("second",)]
    copied.close()


def test_a_second_start_does_nothing(root: Path) -> None:
    move = make_move(root)
    make_old_data_folder(move.old)
    move_folder(move, serving=never)
    before = (tree(move.new), tree(root / f"harness{BACKUP_SUFFIX}"), move.old.readlink())

    assert move_folder(move, serving=never) is None

    assert (tree(move.new), tree(root / f"harness{BACKUP_SUFFIX}"), move.old.readlink()) == (before)


def test_nothing_happens_without_an_old_folder(root: Path) -> None:
    assert move_folder(make_move(root), serving=never) is None

    assert list(root.iterdir()) == []


def test_a_new_folder_that_is_already_there_is_left_alone(root: Path) -> None:
    move = make_move(root)
    make_old_data_folder(move.old)
    move.new.mkdir()
    original = tree(move.old)

    assert move_folder(move, serving=never) is None

    assert tree(move.old) == original
    assert not move.old.is_symlink()
    assert list(move.new.iterdir()) == []


def test_a_failed_copy_leaves_the_old_folder_untouched(root: Path) -> None:
    move = make_move(root)
    make_old_data_folder(move.old)
    (move.old / "locked.txt").write_text("secret", encoding="utf-8")
    (move.old / "locked.txt").chmod(0o000)

    with pytest.raises(FolderMoveError) as raised:
        move_folder(move, serving=never)

    message = str(raised.value)
    assert message.startswith(f"could not copy {move.old} to {move.new}: ")
    assert message.endswith(f"{move.old} is untouched")
    assert move.old.is_dir()
    assert not move.old.is_symlink()
    assert not move.new.exists()
    assert not (root / f"harness{BACKUP_SUFFIX}").exists()
    # The partial copy is kept, never deleted, and stops the next start until it is removed.
    staging = root / f"nest{STAGING_SUFFIX}"
    assert staging.is_dir()
    with pytest.raises(FolderMoveError, match="did not finish"):
        move_folder(move, serving=never)


def test_an_existing_backup_stops_the_move(root: Path) -> None:
    move = make_move(root)
    make_old_data_folder(move.old)
    (root / f"harness{BACKUP_SUFFIX}").mkdir()

    with pytest.raises(FolderMoveError, match="already exists"):
        move_folder(move, serving=never)

    assert not move.new.exists()
    assert not (root / f"nest{STAGING_SUFFIX}").exists()


def test_a_running_old_daemon_stops_the_move(root: Path) -> None:
    move = make_move(root)
    make_old_data_folder(move.old)
    listener = bind_socket(move.old / "token.sock", listen=True)

    with pytest.raises(FolderMoveError, match="still running") as raised:
        move_folder(move)

    listener.close()
    assert "launchctl bootout gui/" in str(raised.value)
    assert not move.new.exists()
    assert not move.old.is_symlink()


def test_answers_only_for_a_listening_socket(root: Path) -> None:
    stale = bind_socket(root / "stale.sock", listen=False)
    live = bind_socket(root / "live.sock", listen=True)

    assert answers(root / "live.sock") is True
    assert answers(root / "stale.sock") is False
    assert answers(root / "missing.sock") is False

    stale.close()
    live.close()


def test_a_move_stopped_after_the_copy_is_finished(root: Path) -> None:
    """The copy was in place but the old folder was not renamed yet."""
    move = make_move(root)
    make_old_data_folder(move.old)
    shutil.copytree(move.old, move.new, symlinks=True)
    (move.new / MARKER_NAME).write_text(f"{move.old}\n", encoding="utf-8")

    assert move_folder(move, serving=never) is not None

    assert (root / f"harness{BACKUP_SUFFIX}").is_dir()
    assert move.old.readlink() == move.new


def test_a_move_stopped_before_the_link_is_finished(root: Path) -> None:
    move = make_move(root)
    make_old_data_folder(move.old)
    shutil.copytree(move.old, move.new, symlinks=True)
    (move.new / MARKER_NAME).write_text(f"{move.old}\n", encoding="utf-8")
    move.old.rename(root / f"harness{BACKUP_SUFFIX}")

    assert move_folder(move, serving=never) is not None

    assert move.old.readlink() == move.new


def test_a_link_the_user_removed_with_the_backup_is_not_made_again(root: Path) -> None:
    move = make_move(root)
    make_old_data_folder(move.old)
    move_folder(move, serving=never)
    move.old.unlink()
    shutil.rmtree(root / f"harness{BACKUP_SUFFIX}")

    assert move_folder(move, serving=never) is None

    assert not move.old.exists()


def test_a_move_that_cannot_be_finished_says_why(root: Path) -> None:
    move = make_move(root)
    make_old_data_folder(move.old)
    shutil.copytree(move.old, move.new, symlinks=True)
    (move.new / MARKER_NAME).write_text(f"{move.old}\n", encoding="utf-8")
    (root / f"harness{BACKUP_SUFFIX}").mkdir()

    with pytest.raises(FolderMoveError, match="could not finish moving"):
        move_folder(move, serving=never)

    assert move.old.is_dir()
    assert not move.old.is_symlink()


def test_the_old_database_name_is_adopted_with_its_wal_and_shm(root: Path) -> None:
    for name in ("harness.db", "harness.db-wal", "harness.db-shm"):
        (root / name).write_text(name, encoding="utf-8")

    assert adopt_legacy_database(root) is True

    assert sorted(path.name for path in root.iterdir()) == ["nest.db", "nest.db-shm", "nest.db-wal"]
    assert (root / "nest.db-wal").read_text(encoding="utf-8") == "harness.db-wal"
    assert adopt_legacy_database(root) is False


def test_an_existing_database_is_never_replaced(root: Path) -> None:
    (root / "harness.db").write_text("old", encoding="utf-8")
    (root / "nest.db").write_text("new", encoding="utf-8")

    assert adopt_legacy_database(root) is False
    assert adopt_legacy_database(root / "missing") is False

    assert (root / "nest.db").read_text(encoding="utf-8") == "new"
    assert (root / "harness.db").read_text(encoding="utf-8") == "old"


def test_the_database_is_not_renamed_under_a_running_daemon(root: Path) -> None:
    (root / "harness.db").write_text("old", encoding="utf-8")
    listener = bind_socket(root / "token.sock", listen=True)

    with pytest.raises(FolderMoveError, match="still running"):
        adopt_legacy_database(root)

    listener.close()
    assert (root / "harness.db").exists()
