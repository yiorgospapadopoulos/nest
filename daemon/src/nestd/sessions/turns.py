"""A session's background work: setup and turns on the agent run."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from nestd.artifacts.tools import ARTIFACT_NOTE
from nestd.attachments.store import Attachment, AttachmentStore
from nestd.clock import Clock
from nestd.config.models import PermissionMode, RepoConfig
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.events.models import Event
from nestd.local.models import is_local
from nestd.local.run import LocalRun
from nestd.providers.base import (
    AgentRun,
    AgentTool,
    ApprovalHandler,
    ResultInfo,
    RewindResult,
    SessionSpec,
    TokenUsage,
)
from nestd.repos.service import RepoService
from nestd.sessions.bookkeeping import isolated, isolated_or
from nestd.sessions.engines import Engine, Engines
from nestd.sessions.errors import NoWorkspaceError
from nestd.sessions.extras import NestToolsSource, RunExtras, RunExtrasSource
from nestd.sessions.hooks import SessionHooks
from nestd.sessions.limits import LimitPauses
from nestd.sessions.live import BYPASS, LiveSession, Unsent
from nestd.sessions.local import LocalSource, crosses_local, require
from nestd.sessions.models import USER, NewSession, Sender, Session, SessionState
from nestd.sessions.queue import MessageQueue
from nestd.sessions.rules import attachment_summary, require_cwd, user_input
from nestd.sessions.sink import SessionSink, TurnEnd
from nestd.sessions.states import StateWriter
from nestd.sessions.steering import Steering
from nestd.sessions.store import SessionStore
from nestd.sessions.subagents import (
    NO_AGENTS,
    CallToolsSource,
    ChatAgents,
    ChatAgentsSource,
    PixieCalls,
)
from nestd.sessions.workspace import prepare_worktree
from nestd.worktrees.manager import WorktreeManager

logger = logging.getLogger(__name__)

# A pixie chat opens a fresh run after a turn that filled this much of the context (D072).
ROTATE_PERCENT = 60

# How long the turn's end waits for the context report, which holds up Nest's reader
# of the agent's messages. The SDK takes control answers in its own reader, which stops
# only once 100 messages wait unread (I-L).
CONTROL_TIMEOUT_SECONDS = 10.0

_CONNECTORS_NOTE = (
    "Mention MCP servers that need authorization or failed to connect only when the user "
    "asks about them or the task needs one of them."
)
# Like the Claude app's agent, plan almost every task: Claude Code's default plans only
# bigger jobs (B47).
_PLAN_NOTE = (
    "Plan with the task list: for any request that edits files or takes more than one step, "
    "your first action is to create every step with TaskCreate (load TaskCreate and "
    "TaskUpdate with ToolSearch first if they are deferred), before any other tool call. "
    "Then keep the list current with TaskUpdate: mark a step in_progress when you start it "
    "and completed as soon as it is done. Skip the list only for a quick question or a "
    "single command."
)
# A chat uses git as in the terminal (B58).
NEST_PROMPT = (
    "You are running inside Nest. Commit when the user asks. Push, open or merge a pull "
    f"request only when the user explicitly asks for it in this chat. {_CONNECTORS_NOTE} "
    f"{_PLAN_NOTE} {ARTIFACT_NOTE}"
)
# A plain folder's work is never reviewed, committed or pushed by Nest (D041).
PLAIN_FOLDER_PROMPT = (
    f"You are running inside Nest, in a folder that is not a git repository. {_CONNECTORS_NOTE} "
    f"{_PLAN_NOTE} {ARTIFACT_NOTE}"
)
# A chat a pixie started, which may commit but whose pushes and pull requests stay blocked
# (D072, B58, D123); a pixie's own runs have their own prompt.
GUARDED_PROMPT = (
    "You are running inside Nest. You may commit your work. Do not run git push, "
    "gh pr create or gh pr merge: the user pushes and opens or merges pull requests. "
    f"{_CONNECTORS_NOTE} {_PLAN_NOTE} {ARTIFACT_NOTE}"
)

# The same for Codex chats, which have no task list but Nest's artifact tools (B91).
CODEX_PROMPT = (
    "You are running inside Nest. Commit when the user asks. Push, open or merge a pull "
    f"request only when the user explicitly asks for it in this chat. {_CONNECTORS_NOTE} "
    f"{ARTIFACT_NOTE}"
)
CODEX_PLAIN_FOLDER_PROMPT = (
    f"You are running inside Nest, in a folder that is not a git repository. {_CONNECTORS_NOTE} "
    f"{ARTIFACT_NOTE}"
)
CODEX_GUARDED_PROMPT = (
    "You are running inside Nest. You may commit your work. Do not run git push, "
    "gh pr create or gh pr merge: the user pushes and opens or merges pull requests. "
    f"{_CONNECTORS_NOTE} {ARTIFACT_NOTE}"
)

# How Claude Code ends a turn when a message written into it arrived as the turn ended: it
# had the message but never answered it (B59).
HANDOFF_ERROR = "[ede_diagnostic] result_type=user"

# The state a background task ends in, and the error that caused it, if any.
type Outcome = tuple[SessionState, str | None]


class TurnRunner:
    """Runs a session's tasks and follows the agent's turns as its run reports them."""

    def __init__(
        self,
        *,
        store: SessionStore,
        bus: EventBus,
        states: StateWriter,
        hooks: SessionHooks,
        worktrees: WorktreeManager,
        repos: RepoService,
        attachments: AttachmentStore,
        engines: Engines,
        handler_for: Callable[[LiveSession], ApprovalHandler],
        on_mode: Callable[[LiveSession, PermissionMode], Awaitable[None]],
        idle_close: timedelta,
        queue: MessageQueue,
        clock: Clock,
        limits: LimitPauses,
        extras: RunExtrasSource | None = None,
        agents: ChatAgentsSource | None = None,
        calls: PixieCalls | None = None,
        nest_tools: NestToolsSource | None = None,
        call_tools: CallToolsSource | None = None,
        local: LocalSource | None = None,
    ) -> None:
        """`on_mode` records a permission mode the engine switched to itself; `limits`
        holds the chats paused at the usage limit (B78); `agents` gives a project chat's
        run its subagents (B40), and `calls` follows the pixies it calls (B46).
        `nest_tools` gives every run the tools all chats and pixies have (B79), and
        `call_tools` the tool that calls the pixies its engine cannot run inside (B91).
        `local` points runs on local models at their servers (B106).
        """
        self._local = local
        self._nest_tools = nest_tools
        self._call_tools = call_tools
        self._limits = limits
        self._on_mode = on_mode
        self._calls = calls
        self._extras = extras
        self._agents = agents
        self._repos = repos
        self._queue = queue
        self._clock = clock
        self._store = store
        self._bus = bus
        self._states = states
        self._hooks = hooks
        self._worktrees = worktrees
        self._attachments = attachments
        self._engines = engines
        self._handler_for = handler_for
        self._idle_close = idle_close
        self.steering = Steering(store, queue, attachments, self._run_fits, self.agent_text)

    async def guard(self, live: LiveSession, work: Coroutine[Any, Any, Outcome | None]) -> None:
        """Run `work` as the session's task. An outcome ends the turn; None means the
        message was submitted and the agent's result will end it.
        """
        outcome: Outcome | None = (SessionState.INTERRUPTED, None)  # if cancelled
        try:
            outcome = await work
        except Exception as exc:
            logger.exception("session %s failed", live.session_id)
            await live.close_run()
            outcome = (SessionState.FAILED, str(exc))
        finally:
            # A queued message may already have started the next task; that one stays.
            if live.task is asyncio.current_task():
                live.task = None
            if outcome is not None:
                await self._conclude(live, *outcome)
            else:
                # Messages sent while its message was being given go into the turn (B59).
                await isolated(
                    "steering waiting messages", live.session_id, self.steering.flush(live)
                )
                # The turn may have ended while its message was still being sent, and a
                # message sent since then waited only for this task (BUG-60).
                live.schedule_idle_close(self._idle_close)
                await self.release_held(live)

    async def start(
        self,
        live: LiveSession,
        session: Session,
        repo: RepoConfig | None,
        attachments: list[Attachment],
        sender: Sender = USER,
        text: str | None = None,
    ) -> Outcome | None:
        """Prepare the worktree a worktree chat does not have yet, then give the agent
        `text`, else the chat's first prompt.
        """
        prompt = session.prompt if text is None else text
        # A chat that joined an existing worktree has it already (B96).
        if session.mode == "worktree" and session.worktree_path is None:
            assert repo is not None  # noqa: S101 (a worktree session always has a project)
            live.preparing = True
            try:
                setup = await prepare_worktree(
                    session, repo, self._worktrees, self._store, self._bus
                )
            except asyncio.CancelledError:
                _keep_unsent(live, Unsent(prompt, attachments, False, sender))
                raise
            finally:
                live.preparing = False
            if setup is not None and not setup.ok:
                return SessionState.FAILED, f"setup command failed: {setup.command}"
        return await self.submit(live, prompt, attachments, sender=sender)

    async def start_later(
        self,
        live: LiveSession,
        session: Session,
        repo: RepoConfig,
        attachments: list[Attachment],
        sender: Sender,
        text: str,
    ) -> Outcome | None:
        """A forked worktree chat's first message: its worktree is made first (B59)."""
        await self._states.set(live.session_id, SessionState.STARTING)
        return await self.start(live, session, repo, attachments, sender, text)

    async def deliver_next(self, live: LiveSession) -> Outcome | None:
        """Start the queue's first message now: Send now on an idle session (B59)."""
        return await self._deliver(live, None, None)

    async def submit(
        self,
        live: LiveSession,
        text: str,
        attachments: list[Attachment],
        shown: bool = False,
        sender: Sender = USER,
    ) -> None:
        """Show the message unless it is `shown` already, and give it to the agent. A nudge
        that cuts it off before the agent has it keeps it to go first (BUG-58).
        """
        try:
            if not shown:
                await self._announce(live, text, attachments, sender)
                shown = True
            await self._run_turn(live, text, attachments)
        except asyncio.CancelledError:
            if not live.turn_active:
                _keep_unsent(live, Unsent(text, attachments, shown, sender))
            raise

    async def _announce(
        self, live: LiveSession, text: str, attachments: list[Attachment], sender: Sender
    ) -> None:
        live.user_event = (await self._show(live, text, attachments, sender)).id

    async def _show(
        self, live: LiveSession, text: str, attachments: list[Attachment], sender: Sender
    ) -> Event:
        """The user message in the transcript."""
        session_id = live.session_id
        await self._attachments.assign([a.id for a in attachments], session_id)
        return await self._bus.publish(
            types.SESSION_USER_MESSAGE,
            {
                "text": text,
                "attachments": [attachment_summary(a) for a in attachments],
                **sender.payload(),
            },
            session_id,
        )

    async def _run_turn(self, live: LiveSession, text: str, attachments: list[Attachment]) -> None:
        session = await self._start_turn(live)
        cwd = require_cwd(session)
        if not cwd.is_dir():
            # The turn fails before the agent gets the message (B61).
            msg = f"the working directory {cwd} does not exist"
            raise NoWorkspaceError(msg)
        await isolated("the turn start hooks", live.session_id, self._hooks.turn_starting(session))
        run = await self._ensure_run(live, session, cwd)
        live.turn_active = True
        await run.send(user_input(await self.agent_text(live, text), attachments))

    async def agent_text(self, live: LiveSession, text: str) -> str:
        """`text` as the agent gets it: teams it calls get their instruction (B40), and
        pixies it calls again are continued (B46). The chat shows what was typed.
        """
        agents = live.run_agents
        if self._calls is None:
            return agents.message(text)
        note = await isolated_or(
            "the pixie notes", live.session_id, self._calls.note(live.session_id, agents, text), ""
        )
        return agents.message(text) + note

    async def agent_active(self, live: LiveSession) -> None:
        # A turn the agent starts on its own waits while the daemon publishes its work or
        # files are restored (BUG-89).
        await live.published.wait()
        await live.unheld.wait()
        if live.busy:
            return
        # The agent started a turn on its own, e.g. after a background task finished.
        live.turn_active = True
        live.cancel_idle_close()
        await self._start_turn(live)

    async def _start_turn(self, live: LiveSession) -> Session:
        """The agent gets a message or starts on its own; clients time the turn from here."""
        live.turn_started = self._clock.now()
        return await self._states.set(
            live.session_id, SessionState.RUNNING, turn={"turn_start": True}
        )

    async def how_ended(self, live: LiveSession, info: ResultInfo) -> TurnEnd | None:
        """Why the turn ended when that was no failure (B59): the user stopped it, the
        usage limit cut it off (B78), or it ends only so that the next message starts (a
        handoff): Send now stopped it, or Claude Code ended it with messages written into
        it and the last one unanswered.
        """
        if live.interrupted:
            return "handoff" if live.resume_queue else "stopped"
        if await self._limited(live, info):
            return "limit"
        if not any(HANDOFF_ERROR in error for error in info.errors):
            return None
        return "handoff" if await self._queue.sent_ids(live.session_id) else None

    async def _limited(self, live: LiveSession, info: ResultInfo) -> bool:
        """Whether the usage limit cut the turn off: it reported the limit and its message
        was cut off, or it ended with an error. A habit run is not paused: it fails (B78);
        neither is a called pixie, whose caller waits for it (B91).
        """
        hit = live.limit_hit
        if hit is None or not (hit.cut_off or info.is_error):
            return False
        session = await self._store.get(live.session_id)
        return session.habit_run_id is None and session.called_by is None

    async def turn_finished(
        self, live: LiveSession, error: str | None, end: TurnEnd | None
    ) -> None:
        """Report the turn, then end it or deliver the next queued message. The reports are
        bookkeeping: their failure never keeps the turn open. A turn the engine ended with
        an error fails, unless it ended for the next message (a handoff) or at the usage
        limit, which pauses the chat (B78); the run stays for the next message.

        Messages written into the turn that the agent did not read are taken back to wait
        for the next turn. One it read without echoing it yet starts the agent's next turn
        after a turn that ended normally, so the session goes on running; after a Stop, a
        failure or a handoff it was lost with the turn and waits for a turn again, which
        after a handoff starts at once (B59).
        """
        session_id = live.session_id
        run = live.run
        hit, live.limit_hit = live.limit_hit, None
        if run is not None:
            await isolated("the context report", session_id, self._report_context(live, run))
        handoff = end == "handoff"
        paused = end == "limit" and hit is not None and not live.interrupted and not live.stopped
        if live.interrupted:
            state, error = SessionState.INTERRUPTED, None
        elif handoff or paused:
            state, error = SessionState.IDLE, None
        elif error is not None:
            state = SessionState.FAILED
        else:
            state = SessionState.IDLE
        async with live.steering:
            taken = await self._retract(live)
            going_on = (
                bool(taken)
                and state is SessionState.IDLE
                and not live.stopped
                and not handoff
                and not paused
            )
            if going_on:
                live.engine_next = True
            else:
                await isolated(
                    "the messages lost with the turn",
                    session_id,
                    self._queue.mark_sent(session_id, taken, False),
                )
                # Until the turn has ended, a message sent waits for it, as before.
                live.concluding = True
        if paused:
            assert hit is not None  # noqa: S101 (set whenever the turn pauses)
            # Before the turn ends, so its end leaves the queue waiting (B78).
            await isolated("the usage limit pause", session_id, self._limits.pause(session_id, hit))
        if not going_on:
            try:
                await self._conclude(live, state, error)
            finally:
                live.concluding = False
        if run is not None:
            # Nothing waits for it, so it waits beside the reader (I-L).
            live.report(
                isolated(
                    "the connector report", session_id, self._report_connectors(session_id, run)
                )
            )

    async def message_taken(self, live: LiveSession, message_id: str, checkpoint_id: str) -> None:
        """The agent read a message written into the turn: it shows where it was read. One
        it starts its next turn with is that turn's message, so the turn starts as one Nest
        gave it (B56): the work is noted before it (B59).
        """
        queued = await self._queue.take(live.session_id, message_id)
        if queued is None:
            return  # taken back meanwhile, or from before a restart
        new_turn = live.engine_next or not live.turn_active
        if new_turn:
            live.engine_next = False
            live.turn_active = True
            live.cancel_idle_close()
        ids = [attachment.id for attachment in queued.attachments]
        attachments = await self._attachments.for_session(ids, live.session_id)
        event = await self._show(live, queued.text, attachments, queued.sender)
        assert event.id is not None  # noqa: S101 (a stored event)
        await self._store.save_checkpoint(live.session_id, event.id, checkpoint_id)
        if new_turn:
            session = await self._start_turn(live)
            await isolated(
                "the turn start hooks", live.session_id, self._hooks.turn_starting(session)
            )

    async def run_stopped(self, live: LiveSession, error: str) -> None:
        # The run already closed itself; the next message opens a new one and resumes.
        live.run = None
        live.limit_hit = None
        # Its background tasks ended with it; a stale count would keep later runs open.
        live.background_tasks = 0
        live.engine_next = False
        # Messages written into it that it never echoed wait for the next turn (B59).
        await isolated(
            "the messages written into the run",
            live.session_id,
            self._queue.unsend_all(live.session_id),
        )
        if live.turn_active:
            await self._end_turn(live, SessionState.FAILED, error)

    async def background_tasks(self, live: LiveSession, running: int) -> None:
        live.background_tasks = running
        live.schedule_idle_close(self._idle_close)

    async def permission_mode(self, live: LiveSession, mode: PermissionMode) -> None:
        await self._on_mode(live, mode)

    async def checkpoint(self, live: LiveSession, checkpoint_id: str) -> None:
        """Keep the checkpoint of the user message the agent was last given (IMP-02)."""
        event_id, live.user_event = live.user_event, None
        if event_id is not None:
            await self._store.save_checkpoint(live.session_id, event_id, checkpoint_id)

    async def rewind(self, live: LiveSession, checkpoint_id: str, dry_run: bool) -> RewindResult:
        """Restore files to `checkpoint_id` on the session's run, resuming the agent's last
        session when the run was closed; the session counts as busy meanwhile.
        """
        try:
            async with live.hold():
                session = await self._store.get(live.session_id)
                run = await self._ensure_run(live, session, require_cwd(session))
                return await run.rewind_files(checkpoint_id, dry_run)
        finally:
            live.schedule_idle_close(self._idle_close)
            await self.release_held(live)

    async def open_run(self, live: LiveSession) -> AgentRun:
        """The session's run as its next message would get it: a rewound conversation's
        is opened cut, so Claude Code loads, or refuses, the cut at once (B59). The
        caller holds the session (`live.hold`) and then calls `released`.
        """
        session = await self._store.get(live.session_id)
        return await self._ensure_run(live, session, require_cwd(session))

    async def released(self, live: LiveSession) -> None:
        """After a hold: close the run later when idle, and start what waited for it."""
        live.schedule_idle_close(self._idle_close)
        await self.release_held(live)

    async def release_held(self, live: LiveSession) -> None:
        """Start the queue on an idle session when a message waited only for publishing or
        a finishing send (BUG-60, BUG-61); one held by a Stop or a failure keeps waiting.
        """
        if not live.held or live.busy or live.publishing or live.stopped or self._paused(live):
            return
        # Starting clears `held`; any turn's end clears it too.
        if await self._has_queued(live) and not live.busy and not live.publishing:
            live.start(lambda: self.guard(live, self._deliver(live, None, None)))

    async def _conclude(self, live: LiveSession, state: SessionState, error: str | None) -> None:
        """End the turn in `state`, or go straight on with the next queued message, so the
        session never rests in between: after a turn that ended normally, or one the user
        interrupted to send a message (a nudge) right away (D032, D036). Otherwise the queue
        waits: the user stopped the agent on purpose, or the failure should show.
        """
        resume = state is SessionState.IDLE or (
            state is SessionState.INTERRUPTED and live.resume_queue
        )
        queued = resume and (live.unsent is not None or await self._has_queued(live))
        queued = queued and not live.stopped  # closing: nothing new starts (BUG-53)
        queued = queued and not self._paused(live)  # until the usage limit resets (B78)
        if live.interrupted and state is SessionState.IDLE:
            # Stop was pressed while the queue was read: it was accepted, so it holds (BUG-59).
            state, queued = SessionState.INTERRUPTED, queued and live.resume_queue
        if not queued:
            await self._end_turn(live, state, error)
            return
        # The next turn starts once its message is sent; Stop until then cancels it.
        live.turn_active = False
        live.interrupted = live.resume_queue = False
        previous = live.task
        live.task = asyncio.create_task(
            self.guard(live, self._deliver(live, previous, (state, error)))
        )

    def _paused(self, live: LiveSession) -> bool:
        return self._limits.paused(live.session_id)

    async def _retract(self, live: LiveSession) -> list[str]:
        """`Steering.retract`; bookkeeping, so a failure leaves the messages as they are."""
        try:
            return await self.steering.retract(live)
        except Exception as error:
            logger.warning(
                "taking back the messages of session %s failed (%s)", live.session_id, error
            )
            return []

    async def _has_queued(self, live: LiveSession) -> bool:
        """Whether messages wait for a turn; ones written into the turn do not (B59)."""
        try:
            return bool(await self._queue.waiting(live.session_id))
        except Exception as error:
            # Bookkeeping: the turn still ends (D048).
            logger.warning("reading the queue of session %s failed (%s)", live.session_id, error)
            return False

    async def _deliver(
        self, live: LiveSession, previous: asyncio.Task[None] | None, ended: Outcome | None
    ) -> Outcome | None:
        """Send the next queued message; `ended` is the outcome if none is left by then."""
        if previous is not None:
            # The task that submitted the turn just ended may still be finishing. A Stop
            # meanwhile cancels only this wait, not that task (BUG-64).
            await asyncio.wait({previous})
        unsent, live.unsent = live.unsent, None
        if unsent is not None:
            await self.submit(live, unsent.text, unsent.attachments, unsent.shown, unsent.sender)
            return None
        taking = asyncio.ensure_future(self._take(live))
        try:
            taken = await asyncio.shield(taking)
        except asyncio.CancelledError:
            # Stopped as the message comes off the queue: it is shown, like a message
            # sent just before Stop, rather than lost.
            await asyncio.gather(taking, return_exceptions=True)
            raise
        if taken is None:
            return ended  # the user took it off the queue meanwhile
        text, attachments = taken
        await self.submit(live, text, attachments, shown=True)
        return None

    async def _take(self, live: LiveSession) -> tuple[str, list[Attachment]] | None:
        queued = await self._queue.pop(live.session_id)
        if queued is None:
            return None
        ids = [attachment.id for attachment in queued.attachments]
        attachments = await self._attachments.for_session(ids, live.session_id)
        await self._announce(live, queued.text, attachments, queued.sender)
        return queued.text, attachments

    async def _report_context(self, live: LiveSession, run: AgentRun) -> None:
        """How full the context window is after the turn, for the session's meter."""
        async with asyncio.timeout(CONTROL_TIMEOUT_SECONDS):
            usage = await run.context_usage()
        if usage is None:
            return
        session_id = live.session_id
        session = await self._store.update(session_id, context=usage)
        await self._bus.publish(
            types.SESSION_CONTEXT, {"context": usage.model_dump(mode="json")}, session_id
        )
        if session.pixie_id is not None and usage.percent >= ROTATE_PERCENT:
            live.rotate = True

    async def _end_turn(self, live: LiveSession, state: SessionState, error: str | None) -> None:
        # Free the session before announcing the outcome, so a client reacting to the
        # new state can send the next message straight away; it starts once the hooks,
        # which make the turn's review, are done.
        details = None if error is None else await self._local_down(live)
        duration = live.turn_ms(self._clock.now())
        live.end_turn(held=state is SessionState.IDLE)
        live.settled.clear()
        try:
            await self._states.set(
                live.session_id, state, error, turn={"duration_ms": duration}, details=details
            )
        finally:
            live.settled.set()
            # Only once the end is announced: closing the run cancels its reader, which this
            # may run in, and a slow store would lose the announcement (B99).
            live.schedule_idle_close(self._idle_close)

    async def _local_down(self, live: LiveSession) -> dict[str, JsonValue] | None:
        """A turn on a local model failed: whether its server went away, asked now, so
        clients offer to start it (B106).
        """
        local = self._local
        if local is None:
            return None

        async def check() -> dict[str, JsonValue] | None:
            model = (await self._store.get(live.session_id)).model
            return await local.down(model) if is_local(model) else None

        return await isolated_or("the local server check", live.session_id, check(), None)

    async def _report_connectors(self, session_id: str, run: AgentRun) -> None:
        """MCP connections have settled by the end of a turn, unlike at the run's start."""
        servers = await run.connector_statuses()
        await self._hooks.connectors_reported(session_id, servers)

    async def apply_controls(self, live: LiveSession) -> None:
        """Bring the live run to the session's saved model and permission mode. Without a
        run there is nothing to do: a run that is opening applies them once open.
        """
        async with live.controls:
            run = live.run
            if run is not None:
                await _apply_controls(live, run, await self._store.get(live.session_id))

    async def _ensure_run(self, live: LiveSession, session: Session, cwd: Path) -> AgentRun:
        """The live run, or a new one resuming the agent's last session. Controls saved
        while a run opens apply once it is open, so the saved ones always win (D048).
        """
        dirs = await self._attachments.file_dirs(session.id)
        agents = await self.chat_agents(session)
        engine = self._engines.of(session)
        while (run := live.run) is None or not _fits(
            live, session, dirs, agents, _account(engine, session)
        ):
            await live.close_run()
            # Cleared before the extras are read: a change saved while this run opens
            # sets it again, and the loop opens another run with that change.
            live.rotate = False
            extras = await self._pixie_extras(session)
            # Following Claude Code's own mode, the run opens without one (IMP-06).
            mode = None if session.follows_claude_code_mode else session.permission_mode
            local = await self._local_run(live, session)
            # A local run signs in to nothing; the user's own setup still loads (B106).
            account = None if local is not None else await engine.prepare_account()
            spec = SessionSpec(
                cwd=cwd,
                permission_mode=mode,
                model=session.model if local is None else local.model,
                # A local model without thinking takes no thinking level.
                effort=session.effort if local is None or local.thinking else None,
                # A pixie never resumes: each run starts fresh with its memory (D072). A
                # rewound or forked conversation resumes cut (B59).
                resume_id=None if extras else (session.fork_from or session.provider_session_id),
                resume_at=session.fork_at,
                drops_turn=session.fork_drops,
                extra_dirs=dirs + (extras.extra_dirs if extras else ()),
                system_prompt_append=(
                    extras.system_prompt if extras else await self._nest_prompt(session)
                ),
                tools=extras.tools if extras else (),
                nest_tools=self._run_tools(session, agents),
                write_root=extras.write_root if extras else None,
                skills=extras.skills if extras else (),
                subagents=agents.engine_subagents,
                call_rules=agents.rules,
                guard_git=_guarded(session),
                account=account,
                local=local,
            )
            sink = SessionSink(
                live,
                self._bus,
                self._store,
                self,
                self._hooks,
                session.provider_session_id,
                forking=session.fork_from,
                attachments=self._attachments,
                calls=self._calls,
                active_account=engine.active_account,
                local_usage=None if local is None else self._usage_of(local),
            )
            live.run = await engine.provider.open(spec, self._handler_for(live), sink)
            live.run_account = None if account is None else account.id
            live.run_dirs = dirs
            live.run_effort = session.effort
            live.run_bypass = mode == BYPASS
            live.run_model = session.model
            live.run_mode = mode
            live.run_agents = agents
            # A new effort or bypass chosen while it opened needs another run.
            session = await self._store.get(session.id)
        await self.apply_controls(live)
        return run

    async def _local_run(self, live: LiveSession, session: Session) -> LocalRun | None:
        """Where a run on a local model goes, once its server answers and its app loaded
        it with enough context; the chat shows a load as it starts (B106).
        """
        if not is_local(session.model):
            return None
        local = require(self._local)
        await local.require_running(session.model)

        async def notice(text: str) -> None:
            await self._bus.publish(
                types.SESSION_NOTICE, {"kind": "loading_model", "text": text}, live.session_id
            )

        await local.load_model(session.model, notice)
        return await local.run_for(session.model)

    def _usage_of(self, run: LocalRun) -> Callable[[TokenUsage], Awaitable[None]]:
        local = require(self._local)

        async def record(tokens: TokenUsage) -> None:
            await local.record_usage(run.model_id, tokens)

        return record

    async def _pixie_extras(self, session: Session) -> RunExtras | None:
        if session.pixie_id is None:
            return None
        if self._extras is None:
            # Falling back to the project path would resume the old engine session.
            msg = f"pixie chat {session.id} has no run extras source"
            raise RuntimeError(msg)
        return await self._extras(session)

    async def _run_fits(
        self, live: LiveSession, session: Session, folders: tuple[Path, ...]
    ) -> bool:
        """Whether the live run takes a message with files in `folders` as it is (B59)."""
        engine = self._engines.of(session)
        return _fits(
            live, session, folders, await self.chat_agents(session), _account(engine, session)
        )

    async def chat_agents(self, session: NewSession) -> ChatAgents:
        """The pixies the chat may call (B40); a pixie's own chat gets the others (B41).
        An engine without subagents gets none (B91).
        """
        if self._agents is None or not self._engines.of(session).supports("subagents"):
            return NO_AGENTS
        return await self._agents(session)

    def _run_tools(self, session: Session, agents: ChatAgents) -> tuple[AgentTool, ...]:
        """The tools every run has (B79), and the call tool for the pixies it calls as
        sessions of their own (B91). Every engine takes them: Claude in-process, Codex
        from a local MCP server.
        """
        tools = self._nest_tools(session) if self._nest_tools else ()
        calls = self._call_tools(session, agents) if self._call_tools else ()
        return tools + calls

    async def _nest_prompt(self, session: Session) -> str:
        """Without Claude Code's task list (Codex, B91), the prompt leaves out what it says
        about it.
        """
        claude = self._engines.of(session).supports("task_list")
        if _guarded(session):
            return GUARDED_PROMPT if claude else CODEX_GUARDED_PROMPT
        git = await self._repos.has_git(session.repo)
        if git:
            return NEST_PROMPT if claude else CODEX_PROMPT
        return PLAIN_FOLDER_PROMPT if claude else CODEX_PLAIN_FOLDER_PROMPT


def _guarded(session: Session) -> bool:
    """A pixie may commit but never push, open or merge a pull request (D072, D078, D123): its
    chats, habit runs (which carry its `pixie_id`) and the chats it starts keep those blocked
    (B58).
    """
    return session.pixie_id is not None or session.started_by_pixie is not None


def _keep_unsent(live: LiveSession, unsent: Unsent) -> None:
    """A nudge cut the message off (a plain Stop or closing drops it, as it always did)."""
    if live.resume_queue:
        live.unsent = unsent


def _fits(
    live: LiveSession,
    session: Session,
    dirs: tuple[Path, ...],
    agents: ChatAgents,
    account: str | None,
) -> bool:
    """Whether the live run can take the session's next message as it is."""
    # A new attachment folder, a new effort, another set of subagents (B40), another
    # active account (B98), or bypass for a run that did not open in it needs a new run
    # (D046), but waits while background tasks run: closing would stop them. Until then
    # the agent asks before reading a new folder's files.
    needs_bypass = session.permission_mode == BYPASS and not live.run_bypass
    same = (
        not crosses_local(live.run_model, session.model)
        and set(dirs) <= set(live.run_dirs)
        and live.run_effort == session.effort
        and live.run_agents.fingerprint == agents.fingerprint
        and live.run_account == account
    )
    return (same and not needs_bypass and not live.rotate) or live.background_tasks > 0


def _account(engine: Engine, session: Session) -> str | None:
    """The account the session's next run opens on; none for a local model (B106)."""
    return None if is_local(session.model) else engine.active_account()


async def _apply_controls(live: LiveSession, run: AgentRun, session: Session) -> None:
    # A run cannot move to or from a local model's server: its next message opens a new
    # run for it (B106).
    if session.model != live.run_model and not crosses_local(live.run_model, session.model):
        await run.set_model(session.model)
        live.run_model = session.model
    if session.follows_claude_code_mode:
        return  # the engine reports the mode Claude Code's own settings chose
    mode = session.permission_mode
    # A run that did not open in bypass cannot enter it live; the next message reopens
    # it in bypass instead (D046).
    if mode != live.run_mode and (mode != BYPASS or live.run_bypass):
        await run.set_permission_mode(mode)
        live.run_mode = mode
