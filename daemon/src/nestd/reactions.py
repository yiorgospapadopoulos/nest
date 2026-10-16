"""What follows a session's progress: task and agent tracking, reviews, notifications,
token usage, connector status, slash command lists and the engine's models and account.
"""

from collections.abc import Sequence
from typing import Protocol

from nestd.connectors.registry import ConnectorRegistry
from nestd.engine.service import EngineInfo
from nestd.notifications.notifier import Notifier, NotifyKind
from nestd.providers.base import (
    CommandCatalog,
    EngineDetails,
    McpServer,
    ResultInfo,
    UsageInfo,
)
from nestd.repos.service import RepoService
from nestd.review.watch import ReviewWatcher
from nestd.sessions.commands import CommandStore
from nestd.sessions.models import LimitPause, Session, SessionState
from nestd.tracking.service import Tracking
from nestd.tracking.steps import one_line
from nestd.usage.store import UsageStore

MAX_NOTICE_LENGTH = 200
_WINDOW_NAMES = {
    "five_hour": "5-hour",
    "seven_day": "weekly",
    "seven_day_opus": "weekly Opus",
    "seven_day_sonnet": "weekly Sonnet",
    "overage": "extra usage",
}


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
            # A review announces itself; otherwise the user hears the turn finished.
            reviewed = (
                await self._reviewable(session)
                and await self._reviews.turn_ended(session) is not None
            )
            if session.limit_pause is not None:
                # The usage limit cut the turn off: the chat goes on by itself (B78).
                await self._notify(session, "usage_limit", _limit_text(session.limit_pause))
            elif not reviewed:
                await self._notify(session, "finished", tracker.summary or "The turn finished.")
        elif session.state is SessionState.FAILED and not quiet:
            await self._notify(session, "failed", session.last_error or "The session failed.")
        # After the review: a follower sees whether the turn's work is ready for review.
        for follower in self._followers:
            await follower.state_changed(session)

    async def turn_starting(self, session: Session) -> None:
        """Note the work before the agent gets the message, for the turn's end to compare
        with (B56). Queued turns that follow without an idle between are one run: the first
        start counts. A turn the agent starts on its own, say after background work changed
        files, has no start and is reviewed as it is.
        """
        quiet = session.habit_run_id is not None
        if quiet or self._reviews.has_start(session.id):
            return
        if await self._reviewable(session):
            await self._reviews.turn_started(session)

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

    async def rewound(self, session: Session, *, conversation: bool, files: bool) -> None:
        """The task list follows the shorter transcript; restored files change the work,
        so its review is made again, or withdrawn when no work is left (B56, B59).
        """
        if conversation:
            self._tracking.forget(session.id)
            await self._tracking.sync(session.id)
        if files and session.habit_run_id is None and await self._reviewable(session):
            await self._reviews.refresh(session)

    async def purged(self, session_id: str) -> None:
        self._tracking.forget(session_id)
        self._reviews.forget(session_id)
        for follower in self._followers:
            await follower.purged(session_id)

    async def _reviewable(self, session: Session) -> bool:
        """The agent may have made a plain folder a git repository (D041); a plain folder
        and a pixie chat have nothing to review (D072).
        """
        return session.pixie_id is None and await self._repos.has_git(session.repo)

    async def _notify(self, session: Session, kind: NotifyKind, text: str) -> None:
        await self._notifier.notify(
            kind, session.id, session.repo, session.title, one_line(text, MAX_NOTICE_LENGTH)
        )


def _limit_text(pause: LimitPause) -> str:
    window = "" if pause.window is None else f"{_WINDOW_NAMES[pause.window]} "
    return f"Paused at the {window}usage limit. It goes on by itself after the reset."
