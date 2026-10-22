"""B106: whether an engine is signed in, without asking it."""

from pathlib import Path

from nestd.accounts.active import ActiveAccounts
from nestd.accounts.profiles import FirstAccount, Profiles
from nestd.accounts.signed_in import SignedIn
from nestd.accounts.store import AccountStore
from nestd.engine.sign_ins import CODEX, SignInStore
from nestd.storage.db import Database
from tests.fakes import FakeClock


async def test_the_last_answer_counts_else_whether_it_was_ever_seen(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    store = AccountStore(db, clock)
    profiles = Profiles(tmp_path / "profiles", FirstAccount(None, None, None))
    sign_ins = SignInStore(db, clock)
    signed = SignedIn(store, await ActiveAccounts.load(store, profiles), sign_ins)

    # Never asked, never seen.
    assert not await signed.claude()
    assert not await signed.any()

    await sign_ins.record(CODEX)
    assert not await signed.claude()
    assert await signed.any()

    await store.record("claude-main", True, None, None)
    assert await signed.claude()
    await store.record("claude-main", False, None, None)
    await store.record("codex-main", False, None, None)
    assert not await signed.any()
