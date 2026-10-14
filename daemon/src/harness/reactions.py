"""What follows a session's progress: task and agent tracking, reviews, notifications,
token usage, connector status, slash command lists and the engine's models and account.
"""

from collections.abc import Sequence
from typing import Protocol

from harness.connectors.registry import ConnectorRegistry
from harness.engine.service import EngineInfo
from harness.notifications.notifier import Notifier, NotifyKind
from harness.providers.base import (
    CommandCatalog,
    EngineDetails,
    McpServer,
    ResultInfo,
    UsageInfo,
)
from harness.repos.service import RepoService
from harness.review.watch import ReviewWatcher
from harness.sessions.commands import CommandStore
from harness.sessions.models import Session, SessionState
from harness.tracking.service import Tracking
from harness.tracking.steps import one_line
from harness.usage.store import UsageStore

MAX_NOTICE_LENGTH = 200


class StateFollower(Protocol):
    """Follows state changes after the daemon's own reactions, such as pixies' reports."""

    async def state_changed(self, session: Session) -> None: ...

    async def purged(self, session_id: str) -> None: ...


class SessionReactions:
    """The session hooks of the running daemon."""

    def __init__(
        self,
        tracking: Tracking,
        reviews: ReviewWatcher,
        notifier: Notifier,
        usage: UsageStore,
        connectors: ConnectorRegistry,
        commands: CommandStore,
        engine: EngineInfo,
        repos: RepoService,
        followers: Sequence[StateFollower] = (),
    ) -> None:
        self._followers = followers
        self._repos = repos
        self._commands = commands
        self._engine = engine
        self._tracking = tracking
        self._reviews = reviews
        self._notifier = notifier
        self._usage = usage
        self._connectors = connectors

    async def state_changed(self, session: Session) -> None:
        tracker = await self._tracking.sync(session.id)
        # A habit run speaks only through its reports (B42).
        quiet = session.habit_run_id is not None
        if session.state is SessionState.IDLE and not quiet:
            # The agent may have made a plain folder a git repository (D041); a plain
            # folder and a pixie chat have nothing to review (D072).
            git = session.pixie_id is None and await self._repos.has_git(session.repo)
            # A review announces itself; otherwise the user hears the turn finished.
            if not git or await self._reviews.turn_ended(session) is None:
                await self._notify(session, "finished", tracker.summary or "The turn finished.")
        elif session.state is SessionState.FAILED and not quiet:
            await self._notify(session, "failed", session.last_error or "The session failed.")
        # After the review: a follower sees whether the turn's work is ready for review.
        for follower in self._followers:
            await follower.state_changed(session)

    async def message(self, session_id: str) -> None:
        await self._tracking.sync(session_id)

    async def turn_result(self, session_id: str, info: ResultInfo) -> None:
        await self._usage.record_turn(session_id, info.tokens)

    async def usage(self, info: UsageInfo) -> None:
        await self._usage.update_limits(info)

    async def connectors_reported(self, session_id: str, servers: list[McpServer]) -> None:
        await self._connectors.report(session_id, servers)

    async def commands_reported(self, session_id: str, catalog: CommandCatalog) -> None:
        await self._commands.report(session_id, catalog)

    async def engine_reported(self, details: EngineDetails) -> None:
        await self._engine.report(details)

    async def purged(self, session_id: str) -> None:
        self._tracking.forget(session_id)
        for follower in self._followers:
            await follower.purged(session_id)

    async def _notify(self, session: Session, kind: NotifyKind, text: str) -> None:
        await self._notifier.notify(
            kind, session.id, session.repo, session.title, one_line(text, MAX_NOTICE_LENGTH)
        )
