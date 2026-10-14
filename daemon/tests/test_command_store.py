from datetime import timedelta

from nestd.providers.base import AgentInfo, CommandCatalog, SlashCommand
from nestd.sessions.commands import CommandList, CommandStore
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.fakes import FakeClock
from tests.test_session_store import new_session

FULL = CommandCatalog(
    commands=[
        SlashCommand(name="compact", description="Compact the conversation"),
        SlashCommand(name="review", description="Review", argument_hint="<pr>"),
    ],
    agents=[AgentInfo(name="Plan", description="Plans")],
)


async def test_a_full_report_is_kept_for_the_session_and_its_repo(
    db: Database, clock: FakeClock
) -> None:
    sessions = SessionStore(db, clock)
    session = await sessions.create(new_session(repo="web"))
    store = CommandStore(db, clock)

    await store.report(session.id, FULL)

    own = await store.for_session(session.id, "web")
    assert own == CommandList(
        source="session", commands=FULL.commands, agents=FULL.agents, updated_at=clock.now()
    )
    assert (await store.for_repo("web")).source == "repo"
    assert (await store.for_repo("web")).commands == FULL.commands


async def test_names_only_complete_the_known_list(db: Database, clock: FakeClock) -> None:
    sessions = SessionStore(db, clock)
    session = await sessions.create(new_session())
    store = CommandStore(db, clock)
    await store.report(session.id, FULL)
    clock.advance(timedelta(minutes=1))

    names = CommandCatalog(
        commands=[SlashCommand(name="compact"), SlashCommand(name="Init")],
        agents=[AgentInfo(name="Explore"), AgentInfo(name="Plan")],
        partial=True,
    )
    await store.report(session.id, names)

    listed = await store.for_session(session.id, "repo")
    assert listed.commands == [
        SlashCommand(name="compact", description="Compact the conversation"),
        SlashCommand(name="Init"),
        SlashCommand(name="review", description="Review", argument_hint="<pr>"),
    ]
    assert listed.agents == [AgentInfo(name="Explore"), AgentInfo(name="Plan", description="Plans")]
    assert listed.updated_at == clock.now()


async def test_names_only_with_nothing_known_are_kept_as_they_are(
    db: Database, clock: FakeClock
) -> None:
    session = await SessionStore(db, clock).create(new_session())
    store = CommandStore(db, clock)

    await store.report(
        session.id, CommandCatalog(commands=[SlashCommand(name="compact")], partial=True)
    )

    assert (await store.for_session(session.id, "repo")).commands == [SlashCommand(name="compact")]


async def test_sessions_without_a_list_fall_back_to_their_repo(
    db: Database, clock: FakeClock
) -> None:
    sessions = SessionStore(db, clock)
    reported = await sessions.create(new_session())
    fresh = await sessions.create(new_session())
    store = CommandStore(db, clock)
    await store.report(reported.id, FULL)

    fallback = await store.for_session(fresh.id, "repo")
    nothing = await store.for_session(fresh.id, "other")

    assert fallback.source == "repo"
    assert fallback.commands == FULL.commands
    assert nothing == CommandList(source="none")


async def test_reports_for_unknown_or_deleted_sessions_are_dropped(
    db: Database, clock: FakeClock
) -> None:
    sessions = SessionStore(db, clock)
    session = await sessions.create(new_session())
    store = CommandStore(db, clock)
    await store.report(session.id, FULL)

    await sessions.delete(session.id)
    await store.report("nope", FULL)

    assert (await store.for_session(session.id, "nowhere")).source == "none"
    assert (await store.for_session("nope", "nowhere")).source == "none"
    # The repo keeps the list of its last run.
    assert (await store.for_repo("repo")).source == "repo"
