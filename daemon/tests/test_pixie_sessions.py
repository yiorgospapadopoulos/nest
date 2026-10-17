from pathlib import Path

from nestd.sessions.models import NewSession, pixie_repo
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.fakes import FakeClock


def new(repo: str, pixie_id: str | None = None) -> NewSession:
    return NewSession(
        repo=repo,
        title="t",
        prompt="p",
        mode="in_place",
        cwd=Path("/repo"),
        model=None,
        effort=None,
        permission_mode="default",
        provider="fake",
        pixie_id=pixie_id,
    )


async def test_pixie_chats_are_kept_out_of_session_lists(db: Database, clock: FakeClock) -> None:
    await db.execute(
        "INSERT INTO pixies (id, slug, name, mascot, color, permission_mode,"
        " autonomy, project_access, skills, can_call, position, created_at, updated_at)"
        " VALUES ('p1', 'tester', 'Tester', 'sprout', '#8B7CF6', 'default',"
        " 'observe', 'none', '[]', '[]', 0, 'x', 'x')"
    )
    store = SessionStore(db, clock)
    chat = await store.create(new("repo"))
    pixie_chat = await store.create(new(pixie_repo("p1"), "p1"))

    listed = await store.list_sessions()
    fetched = await store.get(pixie_chat.id)

    assert [s.id for s in listed] == [chat.id]
    assert fetched.pixie_id == "p1"
    assert fetched.repo == "pixie:p1"
    assert chat.pixie_id is None
