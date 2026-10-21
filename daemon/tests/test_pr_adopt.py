"""A pull request the agent opened itself is followed like Nest's own (B101)."""

import asyncio
import json
import logging
from pathlib import Path

import pytest

from nestd.config.models import RepoConfig
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.runner import CommandError
from nestd.prs.adopt import PrAdopter
from nestd.repos.service import RepoNotFoundError
from nestd.sessions.models import Session, SessionState
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_runner import PR_URL, FakeRunner
from tests.fakes import FakeClock
from tests.github_support import REPO_URL
from tests.test_session_store import new_session


def listed(number: int, owner: str = "me", name: str = "repo") -> dict[str, object]:
    """A pull request as `gh pr list --json url,number,headRepositoryOwner,headRepository`
    prints it.
    """
    return {
        "headRepository": {"id": "R_kgDOK1a2bw", "name": name},
        "headRepositoryOwner": {"id": "MDQ6VXNlcjEyMzQ1Njc=", "login": owner},
        "number": number,
        "url": f"https://github.com/me/repo/pull/{number}",
    }


FOUND = json.dumps([listed(7)])


class Env:
    def __init__(self, db: Database, clock: FakeClock, tmp_path: Path) -> None:
        self.bus = EventBus(db, clock)
        self.store = SessionStore(db, clock)
        self.runner = FakeRunner()
        self.repo = RepoConfig(name="repo", path=tmp_path, remote_url=REPO_URL)
        self.soon: list[str] = []
        self.adopter = PrAdopter(
            store=self.store,
            bus=self.bus,
            repo=lambda _name: self.repo,
            run=self.runner,
            cwd=tmp_path / "neutral",
            check_soon=self.soon.append,
        )

    async def idle(self, **fields: object) -> Session:
        """A worktree chat on its own branch whose turn just ended."""
        values: dict[str, object] = {
            "worktree_path": Path("/w/nest-1"),
            "branch": "fix-it",
            "state": SessionState.IDLE,
            **fields,
        }
        # A pixie's chat needs its pixie stored, so it is only made up here.
        pixie = values.pop("pixie_id", None)
        session = await self.store.create(new_session())
        session = await self.store.update(session.id, **values)
        return session.model_copy(update={"pixie_id": pixie})

    def lists(self) -> list[tuple[str, ...]]:
        return [call for call in self.runner.calls if call[1:3] == ("pr", "list")]

    async def ended(self, session: Session) -> Session:
        await self.adopter.state_changed(session)
        await self.adopter.settled()
        return await self.store.get(session.id)


@pytest.fixture
def env(db: Database, clock: FakeClock, tmp_path: Path) -> Env:
    return Env(db, clock, tmp_path)


async def test_a_pull_request_the_agent_opened_is_followed(env: Env) -> None:
    env.runner.pr_list = FOUND
    session = await env.idle()

    stored = await env.ended(session)

    assert stored.pr_url == PR_URL
    assert env.lists() == [
        (
            *("gh", "pr", "list", "--repo", "me/repo", "--head", "fix-it", "--author", "@me"),
            *("--state", "open", "--json", "url,number,headRepositoryOwner,headRepository"),
            *("--limit", "5"),
        )
    ]
    opened = [
        e.payload for e in await env.bus.session_events(session.id) if e.type == types.PR_OPENED
    ]
    assert opened == [{"url": PR_URL}]
    assert env.soon == [session.id]


async def test_only_a_pull_request_from_the_chats_own_repository_is_taken(env: Env) -> None:
    # Same branch name in a fork, then the one pushed to the chat's own repository.
    env.runner.pr_list = json.dumps(
        [listed(5, owner="someone"), listed(6, name="other"), listed(8, owner="Me", name="Repo")]
    )
    session = await env.idle()

    stored = await env.ended(session)

    assert stored.pr_url == "https://github.com/me/repo/pull/8"


async def test_pull_requests_from_other_repositories_only_are_ignored(env: Env) -> None:
    # A fork's, and one whose fork was deleted (GitHub gives no head repository).
    gone = {**listed(6), "headRepository": None, "headRepositoryOwner": None}
    env.runner.pr_list = json.dumps([listed(5, owner="someone"), gone])
    session = await env.idle()

    stored = await env.ended(session)

    assert stored.pr_url is None
    assert env.soon == []


async def test_without_a_pull_request_nothing_changes(env: Env) -> None:
    session = await env.idle()

    stored = await env.ended(session)

    assert stored.pr_url is None
    assert len(env.lists()) == 1
    assert env.soon == []


async def test_a_pull_request_another_chat_follows_is_left_to_it(env: Env) -> None:
    env.runner.pr_list = FOUND
    await env.idle(pr_url=PR_URL)
    session = await env.idle()

    stored = await env.ended(session)

    assert stored.pr_url is None
    assert env.soon == []


@pytest.mark.parametrize(
    "fields",
    [
        {"worktree_path": None, "mode": "in_place"},
        {"branch": "main"},
        {"branch": None},
        {"pr_url": "https://github.com/me/repo/pull/3"},
        {"pixie_id": "p1"},
        {"state": SessionState.RUNNING},
    ],
)
async def test_chats_that_cannot_have_their_own_pull_request_are_not_read(
    env: Env, fields: dict[str, object]
) -> None:
    env.runner.pr_list = FOUND
    session = await env.idle(**fields)

    await env.ended(session)

    assert env.lists() == []


async def test_a_project_without_a_github_remote_is_not_read(env: Env) -> None:
    env.repo = env.repo.model_copy(update={"remote_url": None})
    session = await env.idle()

    await env.ended(session)

    assert env.lists() == []


async def test_a_failed_read_is_logged_by_kind_and_changes_nothing(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    env.runner.failures["gh pr list"] = CommandError(["gh"], 1, "HTTP 502 secret detail\n")
    first = await env.idle()
    env.runner.pr_list = "nonsense"
    second = await env.idle()

    with caplog.at_level(logging.WARNING):
        await env.ended(first)
        await env.ended(second)

    assert (await env.store.get(first.id)).pr_url is None
    assert "could not look for a pull request of me/repo (CommandError)" in caplog.text
    assert "(ValidationError)" in caplog.text
    assert "secret" not in caplog.text


async def test_the_read_does_not_hold_up_the_turn_end_and_runs_once_at_a_time(
    env: Env,
) -> None:
    env.runner.pr_list = FOUND
    session = await env.idle()
    release = asyncio.Event()
    env.runner.before["gh pr"] = release.wait

    await env.adopter.state_changed(session)
    await env.adopter.state_changed(session)
    await until(lambda: len(env.lists()) == 1)
    assert (await env.store.get(session.id)).pr_url is None
    release.set()
    await env.adopter.settled()

    assert len(env.lists()) == 1
    assert (await env.store.get(session.id)).pr_url == PR_URL


async def test_a_removed_project_is_not_read(env: Env) -> None:
    def gone(name: str) -> RepoConfig:
        raise RepoNotFoundError(name)

    env.adopter = PrAdopter(
        store=env.store,
        bus=env.bus,
        repo=gone,
        run=env.runner,
        cwd=env.repo.path,
        check_soon=env.soon.append,
    )

    await env.ended(await env.idle())

    assert env.lists() == []


@pytest.mark.parametrize("meanwhile", ["deleted", "opened"])
async def test_a_chat_deleted_or_given_a_pull_request_meanwhile_is_left_alone(
    env: Env, meanwhile: str
) -> None:
    env.runner.pr_list = FOUND
    session = await env.idle()

    async def change() -> None:
        if meanwhile == "deleted":
            await env.adopter.purged(session.id)
            await env.store.delete(session.id)
        else:
            await env.store.update(session.id, pr_url="https://github.com/me/repo/pull/9")

    env.runner.before["gh pr"] = change
    await env.adopter.state_changed(session)
    await env.adopter.settled()

    assert env.soon == []
