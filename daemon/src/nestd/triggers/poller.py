"""Polls GitHub for the events that habits and project triggers wait for (B148, D177).

Polling, not webhooks: Nest listens only on 127.0.0.1, so GitHub cannot reach it. A loop
checks every 15 seconds which feeds are due. A repository's events feed is read while a
trigger waits for issues, pull requests, comments or reviews in it, and its finished CI
runs while one waits for CI. Each feed is read every minute, every five once nothing new
came for an hour, and after a failure it waits twice as long each time up to 15 minutes
(GitHub's rate limit: 15 minutes at once). Feeds are asked for with their ETag, so an
unchanged one costs nothing.

An event counts once per habit or trigger (dedupe in `TriggerStore`), only if it happened
after the habit or trigger started waiting for it as it is now, and at most a day ago. By
default only people with write access to the repository count (`WriteAccess`, D179).
"""

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import JsonValue, ValidationError

from nestd.clock import Clock
from nestd.config.models import RepoConfig
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.runner import CommandError, CommandRunner
from nestd.issues.service import github_repo_of
from nestd.pixies.habit_store import HabitStore, StoredHabit
from nestd.pixies.scheduler import HabitScheduler
from nestd.prs.untrusted import one_line
from nestd.triggers.access import WriteAccess
from nestd.triggers.chats import TriggeredChats
from nestd.triggers.github import (
    Feed,
    RateLimitedError,
    fetch_feed,
    fetch_pull,
    parse_events,
    parse_runs,
    with_pull,
)
from nestd.triggers.matching import first_match, matches
from nestd.triggers.models import ChatTrigger, EventFilter, GitHubEvent
from nestd.triggers.store import TriggerStore, chat_owner, habit_owner

logger = logging.getLogger(__name__)

TICK = timedelta(seconds=15)
FAST = timedelta(minutes=1)
SLOW = timedelta(minutes=5)
SLOW_AFTER = timedelta(hours=1)
MOST_BACKOFF = timedelta(minutes=15)
# Older events never start anything, as after the Mac slept for days.
MAX_AGE = timedelta(days=1)
PRUNE_EVERY = timedelta(hours=1)
# Characters of an event's text a habit run's message quotes.
HABIT_TEXT_CHARS = 300
_CI = frozenset({"ci_failed", "ci_passed"})


@dataclass(frozen=True)
class _Watcher:
    """A habit or a project trigger, with the projects it watches."""

    owner: str
    rule: EventFilter
    projects: tuple[RepoConfig, ...]
    since: datetime
    habit: StoredHabit | None = None
    trigger: ChatTrigger | None = None


@dataclass
class _FeedState:
    etag: str | None = None
    due: datetime | None = None
    failures: int = 0
    last_new: datetime | None = None


@dataclass
class _Poll:
    """One read of a feed: the pull requests read for it, by number."""

    pulls: dict[int, GitHubEvent | None] = field(default_factory=dict[int, GitHubEvent | None])
    # A pull request or an author's access could not be read: the next read asks for the
    # whole feed again.
    unread: bool = False


class GitHubPoller:
    def __init__(
        self,
        *,
        repos: Callable[[], list[RepoConfig]],
        habits: HabitStore,
        scheduler: HabitScheduler,
        chats: TriggeredChats,
        store: TriggerStore,
        bus: EventBus,
        run: CommandRunner,
        cwd: Path,
        clock: Clock,
        access: WriteAccess,
        tick: timedelta = TICK,
    ) -> None:
        """`run` runs gh with the user's login; `cwd` is a folder outside any repository;
        `access` tells who has write access, whose events count by default.
        """
        self._repos = repos
        self._habits = habits
        self._scheduler = scheduler
        self._chats = chats
        self._store = store
        self._bus = bus
        self._run = run
        self._cwd = cwd
        self._clock = clock
        self._access = access
        self._tick = tick
        self._feeds: dict[tuple[str, Feed], _FeedState] = {}
        self._pruned: datetime | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def tick(self) -> None:
        now = self._clock.now()
        watchers = await self._watchers()
        await self._store.keep_only(w.owner for w in watchers)
        wanted: dict[tuple[str, Feed], list[_Watcher]] = {}
        for watcher in watchers:
            feeds: set[Feed] = set()
            if _CI & set(watcher.rule.events):
                feeds.add("runs")
            if set(watcher.rule.events) - _CI:
                feeds.add("events")
            for project in watcher.projects:
                where = github_repo_of(project)
                if where is None:
                    continue
                for feed in feeds:
                    wanted.setdefault((where, feed), []).append(watcher)
        # Feeds nobody waits for are forgotten, so a new watcher reads them at once.
        self._feeds = {key: self._feeds.get(key, _FeedState()) for key in wanted}
        for (where, feed), waiting in wanted.items():
            state = self._feeds[(where, feed)]
            if state.due is not None and state.due > now:
                continue
            await self._read(where, feed, state, waiting, now)
        if self._pruned is None or now - self._pruned >= PRUNE_EVERY:
            self._pruned = now
            await self._store.prune()

    async def _watchers(self) -> list[_Watcher]:
        repos = self.on_github(self._repos())
        found: list[_Watcher] = []
        for habit in await self._habits.enabled():
            if not habit.github:
                continue
            owner = habit_owner(habit.id)
            config = json.dumps([w.model_dump(mode="json") for w in habit.github])
            since = await self._store.since(owner, config)
            for watch in habit.github:
                named = set(watch.projects)
                projects = tuple(r for r in repos if not named or r.name in named)
                found.append(_Watcher(owner, watch, projects, since, habit=habit))
        for repo in repos:
            for trigger in repo.triggers:
                if not trigger.enabled:
                    continue
                owner = chat_owner(trigger.id)
                rule = EventFilter.model_validate(
                    trigger.model_dump(include=set(EventFilter.model_fields))
                )
                since = await self._store.since(owner, rule.model_dump_json())
                found.append(_Watcher(owner, rule, (repo,), since, trigger=trigger))
        return found

    @staticmethod
    def on_github(repos: list[RepoConfig]) -> list[RepoConfig]:
        return [repo for repo in repos if repo.git and github_repo_of(repo) is not None]

    async def _read(
        self,
        where: str,
        feed: Feed,
        state: _FeedState,
        waiting: list[_Watcher],
        now: datetime,
    ) -> None:
        try:
            answer = await fetch_feed(self._run, self._cwd, where, feed, state.etag)
            events = (
                None
                if answer.body is None
                else parse_events(answer.body, where)
                if feed == "events"
                else parse_runs(answer.body, where)
            )
        except RateLimitedError:
            logger.warning("GitHub asked Nest to slow down reading %s", where)
            state.failures += 1
            state.due = now + MOST_BACKOFF
            return
        except (CommandError, OSError, ValidationError) as error:
            # gh output can quote anything, so only the kind of failure is logged.
            logger.warning("could not read the %s of %s (%s)", feed, where, type(error).__name__)
            state.failures += 1
            state.due = now + min(FAST * 2**state.failures, MOST_BACKOFF)
            return
        state.failures = 0
        state.etag = answer.etag
        took = False
        if events is not None:
            poll = _Poll()
            for event in events:
                for watcher in waiting:
                    took = await self._offer(watcher, event, poll, now) or took
            if poll.unread:
                state.etag = None
        if took or state.last_new is None:
            state.last_new = now
        quiet = now - state.last_new >= SLOW_AFTER
        state.due = now + (SLOW if quiet else FAST)

    async def _offer(
        self, watcher: _Watcher, event: GitHubEvent, poll: _Poll, now: datetime
    ) -> bool:
        """Hand the event to the watcher if it is new to it and matches; True if taken."""
        if event.at < watcher.since or now - event.at > MAX_AGE:
            return False
        if not first_match(watcher.rule, event):
            return False
        project = next(p for p in watcher.projects if github_repo_of(p) == event.repo)
        if event.on_pull and event.number is not None:
            read = await self._pull(event, poll)
            if read is None:
                return False
            event = read
        if not matches(watcher.rule, event):
            return False
        if watcher.rule.authors == "members":
            allowed = await self._access.has_write(event.repo, event.author)
            if allowed is None:
                # Asked again with the whole feed next time.
                poll.unread = True
            if not allowed:
                return False
        if not await self._store.claim(watcher.owner, event):
            return False
        if watcher.habit is not None:
            await self._scheduler.queue_trigger(watcher.habit, _habit_entry(event, project))
            return True
        assert watcher.trigger is not None  # noqa: S101 (a watcher is one or the other)
        fired = await self._chats.fire(project, watcher.trigger, event)
        await self._store.settle(
            watcher.owner, event.key, fired.outcome, fired.reason, fired.session_id
        )
        activity = (await self._store.last([watcher.trigger.id])).get(watcher.trigger.id)
        if activity is not None:
            await self._bus.publish(
                types.TRIGGER_ACTIVITY,
                {"repo": project.name, "activity": activity.model_dump(mode="json")},
            )
        return True

    async def _pull(self, event: GitHubEvent, poll: _Poll) -> GitHubEvent | None:
        """The event with its pull request's details; None when it cannot be read now, so
        it is offered again next time.
        """
        assert event.number is not None  # noqa: S101 (the caller checks)
        if event.number not in poll.pulls:
            try:
                body = await fetch_pull(self._run, self._cwd, event.repo, event.number)
                poll.pulls[event.number] = with_pull(event, body)
            except (CommandError, OSError) as error:
                logger.warning("could not read a pull request (%s)", type(error).__name__)
                poll.pulls[event.number] = None
                poll.unread = True
        read = poll.pulls[event.number]
        if read is None:
            return None
        # The pull request's details on this event, which keeps its own key and text.
        return event.model_copy(
            update={"title": read.title, "labels": read.labels, "branch": read.branch}
        )

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as error:
                logger.warning("GitHub trigger check failed (%s)", type(error).__name__)
            await asyncio.sleep(self._tick.total_seconds())


def _habit_entry(event: GitHubEvent, project: RepoConfig) -> dict[str, JsonValue]:
    """The event as a habit run's message lists it."""
    return {
        "source": "github",
        "kind": event.kind,
        "project": project.name,
        "title": event.title,
        "url": event.url,
        "author": one_line(event.author),
        "text": one_line(event.text)[:HABIT_TEXT_CHARS],
        "at": event.at.isoformat(),
    }
