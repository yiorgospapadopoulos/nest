"""Rewinding a chat to before one of the user's messages, and forking a chat from one, as
in Claude Code (IMP-02, B59).

A rewind restores the files the agent changed since the message (code), the conversation
(that message and everything after it leave the chat, and the next message continues from
before it), or both. The conversation is cut in Claude Code by resuming its session only
up to the entry before the message, into a new session (a fork), so the old transcript
stays whole and Claude Code chats, as kept by Claude Code, are never rewritten. The run is
opened cut at once, so Claude Code loads the cut, or refuses it, before Nest drops the
message and what followed from its own transcript. A fork is a new chat whose first run
resumes the original the same way; the original goes on untouched.
"""

import asyncio
from pathlib import Path

from pydantic import JsonValue, TypeAdapter, ValidationError

from nestd.attachments.store import AttachmentStore, UnknownAttachmentError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.events.models import Event
from nestd.providers.base import ForkPoint, RewindResult
from nestd.repos.service import RepoService
from nestd.sessions.bookkeeping import isolated
from nestd.sessions.engines import Engines
from nestd.sessions.errors import CannotRewindError
from nestd.sessions.hooks import SessionHooks
from nestd.sessions.live import LiveSession
from nestd.sessions.models import (
    AttachmentSummary,
    ForkReply,
    NewSession,
    Restore,
    RewindReply,
    Session,
    SessionState,
)
from nestd.sessions.rules import require_cwd
from nestd.sessions.store import SessionStore
from nestd.sessions.turns import TurnRunner
from nestd.worktrees.manager import InvalidBranchError, WorktreeManager

NO_CHECKPOINT = (
    "Nest has no file checkpoint for this message: it was sent before checkpoints were "
    "kept, in Claude Code, or as a command"
)
NO_RUN_TO_PREVIEW = (
    "Claude Code is not running for this chat, so the files to restore cannot be listed. "
    "Send a message to start it again, then try again."
)
NO_PIXIE_RESTORE = (
    "A pixie's chat cannot be rewound: each of its runs starts fresh, so the earlier "
    "ones' checkpoints are gone."
)
NO_CONVERSATION_POINT = (
    "Claude Code's transcript of this chat does not have this message, so the "
    "conversation cannot be rewound to before it"
)

# The transcript a fork copies; the rest belongs to the original chat's run and work.
FORKED_TYPES = frozenset(
    {
        types.SESSION_USER_MESSAGE,
        types.SESSION_MESSAGE,
        types.SESSION_NOTICE,
        types.SESSION_HOOK,
        types.SESSION_RESULT,
        types.SESSION_AGENT_TASK,
    }
)
FORK_SUFFIX = " (fork)"

_SUMMARIES = TypeAdapter(list[AttachmentSummary])


class Rewinds:
    def __init__(
        self,
        *,
        store: SessionStore,
        bus: EventBus,
        engines: Engines,
        turns: TurnRunner,
        hooks: SessionHooks,
        repos: RepoService,
        worktrees: WorktreeManager,
        attachments: AttachmentStore,
    ) -> None:
        self._attachments = attachments
        self._store = store
        self._bus = bus
        self._engines = engines
        self._turns = turns
        self._hooks = hooks
        self._repos = repos
        self._worktrees = worktrees

    async def user_message(self, session_id: str, event_id: int) -> Event | None:
        """The session's `session.user_message` event `event_id`, if it is one."""
        events = await self._bus.session_events(session_id, event_id - 1, event_id + 1)
        return next((e for e in events if e.type == types.SESSION_USER_MESSAGE), None)

    async def preview(
        self,
        live: LiveSession,
        session: Session,
        message: Event,
        checkpoint: str,
        restore: Restore,
    ) -> RewindReply:
        """What the rewind would do; never starts Claude Code (BUG-94)."""
        reply = _reply(RewindResult(can_rewind=True), restore, message)
        if restore != "code" and await self._point(session, checkpoint) is None:
            return RewindReply(can_rewind=False, error=NO_CONVERSATION_POINT, restore=restore)
        if restore == "conversation":
            return reply
        if live.run is None:
            return RewindReply(can_rewind=False, error=NO_RUN_TO_PREVIEW, restore=restore)
        files = _named_from(await self._turns.rewind(live, checkpoint, True), session)
        return _reply(files, restore, message) if files.can_rewind else _refused(files, restore)

    async def rewind(
        self,
        live: LiveSession,
        session: Session,
        message: Event,
        checkpoint: str,
        restore: Restore,
    ) -> RewindReply:
        """Rewind; CannotRewindError when Claude Code cannot, with nothing changed (unless
        the files were restored and only the conversation then failed, which it says).
        """
        point: ForkPoint | None = None
        if restore != "code":
            point = await self._point(session, checkpoint)
            if point is None:
                raise CannotRewindError(NO_CONVERSATION_POINT)
        files: RewindResult | None = None
        try:
            # A message sent meanwhile waits, so no new turn lands among what is dropped.
            async with live.hold():
                if restore != "conversation":
                    run = await self._turns.open_run(live)
                    files = _named_from(await run.rewind_files(checkpoint, False), session)
                    if not files.can_rewind:
                        raise CannotRewindError(files.error or "the files could not be restored")
                if point is not None:
                    await self._cut(live, session, message, checkpoint, point, files is not None)
                if files is not None:
                    await self._bus.publish(
                        types.SESSION_NOTICE,
                        {"kind": "files_restored", "text": _restored_text(files.files_changed)},
                        session.id,
                    )
                await isolated(
                    "the rewind hooks",
                    session.id,
                    self._hooks.rewound(
                        await self._store.get(session.id),
                        conversation=point is not None,
                        files=files is not None,
                    ),
                )
        finally:
            await self._turns.released(live)
        return _reply(files or RewindResult(can_rewind=True), restore, message)

    async def fork(self, source: Session, message: Event, checkpoint: str) -> ForkReply:
        """A new chat in the same project and work mode whose conversation is the source's
        up to before `message`; the message comes back for its composer. An in-place
        chat's fork works in the same folder; a worktree chat's gets its own worktree,
        branched from the source's branch, with its first message.
        """
        point = await self._point(source, checkpoint)
        if point is None:
            raise CannotRewindError(NO_CONVERSATION_POINT)
        text, attachments = _message(message)
        created = await self._store.create(
            NewSession(
                repo=source.repo,
                title=source.title + FORK_SUFFIX,
                prompt=text,
                mode=source.mode,
                cwd=source.cwd if source.mode == "in_place" else None,
                model=source.model,
                effort=source.effort,
                permission_mode=source.permission_mode,
                follows_claude_code_mode=source.follows_claude_code_mode,
                provider=source.provider,
                base_ref=await self._fork_base(source),
            )
        )
        keep = point.keep_through
        session = await self._store.update(
            created.id,
            state=SessionState.IDLE,
            fork_from=None if keep is None else source.provider_session_id,
            fork_at=keep,
            fork_drops=None if keep is None else await self._drops(source.id, message, checkpoint),
        )
        await self._bus.publish(
            types.SESSION_CREATED, {"session": session.model_dump(mode="json")}, session.id
        )
        await self._bus.publish(
            types.SESSION_STATE, {"state": session.state, "error": None}, session.id
        )
        await self._copy_transcript(source.id, session.id, message)
        copies = [await self._copy(source.id, attachment) for attachment in attachments]
        return ForkReply(
            session=session, text=text, attachments=[c for c in copies if c is not None]
        )

    async def _cut(
        self,
        live: LiveSession,
        session: Session,
        message: Event,
        checkpoint: str,
        point: ForkPoint,
        files_restored: bool,
    ) -> None:
        """Cut the conversation and drop the message and what followed from the chat; what
        the cut run says as it opens (its SessionStart hooks) stays.
        """
        await live.close_run()
        last = await self._bus.last_id()
        if point.keep_through is None:
            # Nothing is kept: the next message starts a new conversation. The old one
            # stays this chat's, as after /clear (BUG-41).
            assert session.provider_session_id is not None  # noqa: S101 (it has a point)
            await self._store.keep_earlier_provider_session(session.id, session.provider_session_id)
            await self._store.update(session.id, provider_session_id=None, **_NO_FORK)
        else:
            await self._store.update(
                session.id,
                fork_from=session.provider_session_id,
                fork_at=point.keep_through,
                fork_drops=await self._drops(session.id, message, checkpoint),
            )
            try:
                await self._turns.open_run(live)
            except Exception as error:
                await self._store.update(session.id, **_NO_FORK)
                done = "The files were restored, but " if files_restored else ""
                msg = f"{done}Claude Code could not rewind the conversation: {error}"
                raise CannotRewindError(msg) from error
        assert message.id is not None  # noqa: S101 (a stored event)
        await self._store.drop_events(session.id, message.id, last)
        text, attachments = _message(message)
        await self._bus.publish(
            types.SESSION_REWOUND,
            {
                "message": message.id,
                "through": last,
                "text": text,
                "attachments": [a.model_dump(mode="json") for a in attachments],
            },
            session.id,
        )

    async def _point(self, session: Session, checkpoint: str) -> ForkPoint | None:
        if session.provider_session_id is None:
            return None
        cwd = require_cwd(session)
        provider = self._engines.of(session).provider
        return await provider.fork_point(cwd, session.provider_session_id, checkpoint)

    async def _drops(self, session_id: str, message: Event, checkpoint: str) -> str | None:
        """The message whose turn the cut drops, so Claude Code checks it drops no more;
        only for the last message: cutting further back drops several turns.
        """
        latest = await self._bus.latest_id(session_id, types.SESSION_USER_MESSAGE)
        return checkpoint if latest == message.id else None

    async def _fork_base(self, source: Session) -> str | None:
        """A worktree fork branches from the source's branch as committed; else from the
        source's own base. An in-place fork compares with HEAD like any new chat.
        """
        if source.mode == "in_place":
            return await self._worktrees.head_at(require_cwd(source))
        if source.branch is None:
            return source.base_ref
        try:
            return await self._worktrees.branch_commit(self._repos.get(source.repo), source.branch)
        except InvalidBranchError:
            return source.base_ref

    async def _copy(self, source_id: str, summary: AttachmentSummary) -> AttachmentSummary | None:
        """A copy of the message's attachment for the fork's composer: the original is the
        source chat's. None when it is gone.
        """
        try:
            (attachment,) = await self._attachments.for_session([summary.id], source_id)
            data = await asyncio.to_thread(attachment.path.read_bytes)
        except (UnknownAttachmentError, OSError):
            return None
        copy = await self._attachments.save(attachment.filename, data, attachment.media_type)
        return AttachmentSummary(
            id=copy.id, filename=copy.filename, media_type=copy.media_type, size=copy.size
        )

    async def _copy_transcript(self, source_id: str, session_id: str, message: Event) -> None:
        events = [
            event
            for event in await self._bus.session_events(source_id, 0, message.id)
            if event.type in FORKED_TYPES
        ]
        copied = await self._bus.publish_many([(e.type, e.payload) for e in events], session_id)
        for original, copy in zip(events, copied, strict=True):
            if original.type != types.SESSION_USER_MESSAGE:
                continue
            assert original.id is not None  # noqa: S101 (stored events)
            assert copy.id is not None  # noqa: S101
            checkpoint = await self._store.checkpoint(source_id, original.id)
            if checkpoint is not None:
                await self._store.save_checkpoint(session_id, copy.id, checkpoint)


_NO_FORK: dict[str, object] = {"fork_from": None, "fork_at": None, "fork_drops": None}


def _message(message: Event) -> tuple[str, list[AttachmentSummary]]:
    text = message.payload.get("text")
    raw: JsonValue = message.payload.get("attachments")
    try:
        attachments = _SUMMARIES.validate_python(raw if isinstance(raw, list) else [])
    except ValidationError:
        attachments = []
    return (text if isinstance(text, str) else ""), attachments


def _reply(files: RewindResult, restore: Restore, message: Event) -> RewindReply:
    """The files' part, and the message for the composer when the conversation goes."""
    text, attachments = _message(message) if restore != "code" else (None, [])
    return RewindReply(**files.model_dump(), restore=restore, text=text, attachments=attachments)


def _named_from(files: RewindResult, session: Session) -> RewindResult:
    """The changed files named from the chat's folder (`src/a.ts`); others stay whole."""
    folder = require_cwd(session)
    names: list[str] = []
    for name in files.files_changed:
        path = Path(name)
        names.append(str(path.relative_to(folder)) if path.is_relative_to(folder) else name)
    return files.model_copy(update={"files_changed": names})


def _refused(files: RewindResult, restore: Restore) -> RewindReply:
    return RewindReply(**files.model_dump(), restore=restore)


def _restored_text(files: list[str]) -> str:
    if not files:
        return "Restored files to before your message"
    count = "1 file" if len(files) == 1 else f"{len(files)} files"
    return f"Restored {count} to before your message"
