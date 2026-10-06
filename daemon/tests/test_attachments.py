import base64
from pathlib import Path

import pytest

from harness.attachments.store import (
    MAX_ATTACHMENT_BYTES,
    AttachmentStore,
    AttachmentTooLargeError,
    UnknownAttachmentError,
    safe_filename,
)
from harness.sessions.store import SessionStore
from harness.storage.db import Database
from tests.fakes import FakeClock
from tests.test_session_store import new_session


@pytest.fixture
def store(db: Database, clock: FakeClock, tmp_path: Path) -> AttachmentStore:
    return AttachmentStore(db, clock, tmp_path / "attachments")


async def test_save_writes_the_file_under_its_id(
    store: AttachmentStore, tmp_path: Path, clock: FakeClock
) -> None:
    attachment = await store.save("../../screen shot.png", b"png-bytes", "image/png")

    assert attachment.path == tmp_path / "attachments" / attachment.id / "screen_shot.png"
    assert attachment.path.read_bytes() == b"png-bytes"
    assert attachment.filename == "screen_shot.png"
    assert attachment.media_type == "image/png"
    assert attachment.size == 9
    assert attachment.session_id is None
    assert attachment.created_at == clock.current
    assert attachment.is_image is True


async def test_media_type_is_guessed_when_missing(store: AttachmentStore) -> None:
    pdf = await store.save("notes.pdf", b"%PDF", None)
    unknown = await store.save("blob", b"?", None)

    assert pdf.media_type == "application/pdf"
    assert pdf.is_image is False
    assert unknown.media_type == "application/octet-stream"


async def test_size_limit(store: AttachmentStore) -> None:
    await store.save("max.bin", b"\0" * MAX_ATTACHMENT_BYTES, None)

    with pytest.raises(AttachmentTooLargeError, match="larger than 20 MB") as caught:
        await store.save("big.bin", b"\0" * (MAX_ATTACHMENT_BYTES + 1), None)
    assert caught.value.status_code == 413


@pytest.mark.parametrize(
    ("name", "expected"),
    [("a b.txt", "a_b.txt"), ("..", "file"), (".env", "env"), ("", "file"), ("é.md", "_.md")],
)
def test_safe_filename(name: str, expected: str) -> None:
    assert safe_filename(name) == expected


def test_safe_filename_caps_the_length() -> None:
    assert safe_filename("x" * 300 + ".txt") == "x" * 96 + ".txt"


async def test_session_attachments(store: AttachmentStore, db: Database, clock: FakeClock) -> None:
    sessions = SessionStore(db, clock)
    one = await sessions.create(new_session())
    two = await sessions.create(new_session())
    image = await store.save("a.png", b"img", "image/png")
    doc = await store.save("b.pdf", b"doc", "application/pdf")
    other = await store.save("c.txt", b"txt", "text/plain")

    found = await store.for_session([image.id, doc.id], one.id)
    await store.assign([image.id, doc.id], one.id)
    await store.assign([other.id], two.id)

    assert found == [image, doc]
    assert await store.for_session([doc.id], one.id) == [
        doc.model_copy(update={"session_id": one.id})
    ]
    assert await store.file_dirs(one.id) == (doc.path.parent,)
    assert await store.file_dirs(two.id) == (other.path.parent,)
    with pytest.raises(UnknownAttachmentError, match="unknown attachment 'missing'"):
        await store.for_session(["missing"], one.id)
    with pytest.raises(UnknownAttachmentError, match="belongs to another session"):
        await store.for_session([other.id], one.id)
    assert await store.for_session([], one.id) == []


async def test_image_data_is_base64(store: AttachmentStore) -> None:
    image = await store.save("a.png", b"\x89PNG", "image/png")

    assert image.read_base64() == base64.b64encode(b"\x89PNG").decode()


async def test_delete_files_removes_only_the_sessions_files(
    store: AttachmentStore, db: Database, clock: FakeClock, tmp_path: Path
) -> None:
    sessions = SessionStore(db, clock)
    one = await sessions.create(new_session())
    two = await sessions.create(new_session())
    mine = await store.save("a.png", b"img", "image/png")
    gone = await store.save("gone.txt", b"x", "text/plain")
    theirs = await store.save("c.txt", b"txt", "text/plain")
    await store.assign([mine.id, gone.id], one.id)
    await store.assign([theirs.id], two.id)
    gone.path.unlink()
    # A row pointing outside the attachments dir is never followed.
    await db.execute(
        "INSERT INTO attachments (id, session_id, filename, media_type, path, size, created_at)"
        " VALUES ('x', ?, 'f', 'text/plain', ?, 1, ?)",
        (one.id, str(tmp_path / "outside" / "f"), clock.now().isoformat()),
    )
    (tmp_path / "outside").mkdir()

    await store.delete_files(one.id)

    assert not mine.path.parent.exists()
    assert not gone.path.parent.exists()
    assert theirs.path.is_file()
    assert (tmp_path / "outside").is_dir()
