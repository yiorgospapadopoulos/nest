"""What follows a session's progress: task and agent tracking, reviews, notifications,
token usage, connector status, slash command lists and the engine's models and account.
"""

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from nestd.connectors.registry import ConnectorRegistry
from nestd.engine.service import EngineInfo
from nestd.notifications.notifier import Notifier, NotifyKind
from nestd.providers.base import (
    CommandCatalog,
    EngineDetails,
    McpServer,
    ResultInfo,
    TokenUsage,
    UsageInfo,
)
from nestd.repos.service import RepoService
from nestd.review.hold import ReviewHold
from nestd.review.watch import ReviewWatcher
from nestd.sessions.commands import CommandStore
from nestd.sessions.errors import SessionNotFoundError
from nestd.sessions.models import LimitPause, Session, SessionState
from nestd.tracking.service import Tracking
from nestd.tracking.steps import one_line
from nestd.tracking.tracker import SessionTracker
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
        session: Callable[[str], Awaitable[Session]],
        followers: Sequence[StateFollower] = (),
    ) -> None:
        self._holds = ReviewHold(self._settle)
        self._session = session
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
        quiet = _quiet(session)
        if session.state is SessionState.IDLE and not quiet:
            await self._turn_ended(session, tracker, notify=True)
        elif session.state is SessionState.FAILED and not quiet:
            await self._notify(session, "failed", session.last_error or "The session failed.")
        # After the review: a follower sees whether the turn's work is ready for review.
        for follower in self._followers:
            await follower.state_changed(session)

    async def autopilot_ended(self, session: Session, text: str) -> None:
        """What the run did goes to review, unless the chat is still in a turn; the user
        hears once.
        """
        if session.habit_run_id is not None or session.called_by is not None:
            return
        if session.state is SessionState.IDLE:
            if (await self._tracking.sync(session.id)).agents.helpers_working():
                await self._hold(session, notify=False)
            elif await self._reviewable(session):
                await self._reviews.turn_ended(session)
        await self._notify(session, "finished", text)

    async def turn_starting(self, session: Session) -> None:
        """Note the work before the agent gets the message, for the turn's end to compare
        with (B56). Queued turns that follow without an idle between are one run: the first
        start counts. A turn the agent starts on its own, say after background work changed
        files, has no start and is reviewed as it is. So is a chat waiting for its helpers,
        whose work is not this turn's alone (B133).
        """
        quiet = _quiet(session)
        if quiet or self._reviews.has_start(session.id) or self._holds.holds(session.id):
            return
        if await self._reviewable(session):
            await self._reviews.turn_started(session)

    async def message(self, session_id: str) -> None:
        tracker = await self._tracking.sync(session_id)
        if not tracker.agents.helpers_working():
            self._holds.helpers_ended(session_id)

    async def helpers_lost(self, session_ids: Sequence[str]) -> None:
        """On start: these chats' helpers ended with the previous process (B133)."""
        for session_id in session_ids:
            await self._settle(session_id, True)

    def shutdown(self) -> None:
        self._holds.shutdown()

    async def turn_result(self, session_id: str, info: ResultInfo) -> None:
        await self._usage.record_turn(session_id, info.tokens)

    async def usage(self, info: UsageInfo, account_id: str | None) -> None:
        await self._usage.update_limits(info, account_id)

    async def subagent_usage(self, session_id: str, message_id: str, tokens: TokenUsage) -> None:
        await self._usage.record_subagent(session_id, message_id, tokens)

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

    async def moved(self, session: Session) -> None:
        """What the new folder holds already is not the chat's work: only what later
        turns change there is (B119).
        """
        if await self._reviewable(session):
            await self._reviews.moved(session)

    async def purged(self, session_id: str) -> None:
        self._holds.release(session_id)
        self._tracking.forget(session_id)
        self._reviews.forget(session_id)
        for follower in self._followers:
            await follower.purged(session_id)

    async def _turn_ended(self, session: Session, tracker: SessionTracker, *, notify: bool) -> None:
        """A review announces itself; otherwise the user hears the turn finished. While
        helpers work the chat is not done, so both wait for them (B133).
        """
        helpers = tracker.agents.helpers_working()
        if helpers:
            await self._hold(session, notify=notify)
        else:
            self._holds.release(session.id)
        reviewed = (
            not helpers
            and await self._reviewable(session)
            and await self._reviews.turn_ended(session) is not None
        )
        if session.limit_pause is not None:
            # The usage limit cut the turn off: the chat goes on by itself (B78).
            await self._notify(session, "usage_limit", _limit_text(session.limit_pause))
        elif notify and not helpers and not reviewed:
            await self._notify(session, "finished", tracker.summary or "The turn finished.")

    async def _hold(self, session: Session, *, notify: bool) -> None:
        self._holds.hold(session.id, notify=notify)
        if await self._reviewable(session):
            await self._reviews.held(session)

    async def _settle(self, session_id: str, notify: bool) -> None:
        """The chat's helpers ended and no turn followed. A running turn settles the chat
        when it ends, as does the turn that follows a usage limit's reset.
        """
        try:
            session = await self._session(session_id)
        except SessionNotFoundError:
            return
        if session.state is not SessionState.IDLE or session.limit_pause is not None:
            return
        if not _quiet(session):
            await self._turn_ended(session, await self._tracking.sync(session_id), notify=notify)

    async def _reviewable(self, session: Session) -> bool:
        """The agent may have made a plain folder a git repository (D041); a plain folder
        and a pixie chat have nothing to review (D072).
        """
        return session.pixie_id is None and await self._repos.has_git(session.repo)

    async def _notify(self, session: Session, kind: NotifyKind, text: str) -> None:
        await self._notifier.notify(
            kind, session.id, session.repo, session.title, one_line(text, MAX_NOTICE_LENGTH)
        )


def _quiet(session: Session) -> bool:
    """A habit run speaks only through its reports (B42), a called pixie through the chat
    that called it (B91), and a chat on Autopilot when its run ends.
    """
    return (
        session.habit_run_id is not None
        or session.called_by is not None
        or session.autopilot is not None
    )


def _limit_text(pause: LimitPause) -> str:
    window = "" if pause.window is None else f"{_WINDOW_NAMES[pause.window]} "
    return f"Paused at the {window}usage limit. It goes on by itself after the reset."
