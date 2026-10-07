"""The Claude Code chats of the registered repos, kept current by polling file times.

A repo's chats are those Claude Code ran in the repo folder or in one of its own worktrees
(`<repo>/.claude/worktrees/<name>`). Chats harness owns are left out: those it runs or
adopted (by session id) and those in its own worktrees (`harness-*`), even once deleted.
Archived chats stay in the list, marked; the archive is harness's own state (D040).
"""

import asyncio
import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import JsonValue

from harness.claude_sessions.archive import ChatArchive
from harness.claude_sessions.errors import ClaudeChatNotFoundError
from harness.claude_sessions.live import LiveChats
from harness.claude_sessions.location import candidate_dirs
from harness.claude_sessions.models import ClaudeChat
from harness.claude_sessions.transcript import Transcript, read_transcript
from harness.config.models import RepoConfig
from harness.events import types
from harness.events.bus import EventBus
from harness.events.models import Event
from harness.repos.service import RepoService
from harness.sessions.models import ChatImport
from harness.sessions.store import SessionStore
from harness.worktrees.manager import WORKTREE_PREFIX, claude_worktrees_dir

logger = logging.getLogger(__name__)

POLL_INTERVAL = timedelta(seconds=10)
# Entrypoints of chats a program started through an Agent SDK (`sdk-py`, `sdk-ts`).
AUTOMATED_PREFIX = "sdk"
_SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

type _Signature = tuple[tuple[str, str, datetime, int, bool, bool], ...]
# Told the whole list after every scan, such as to index the chats' titles.
type ChatsListener = Callable[[list[ClaudeChat]], Awaitable[None]]


@dataclass(frozen=True)
class _Info:
    """What the list needs from one transcript file."""

    title: str
    cwd: Path
    created_at: datetime | None
    message_count: int
    entrypoint: str | None


@dataclass(frozen=True)
class _Cached:
    stamp: tuple[int, int]  # mtime in ns, size
    info: _Info | None


@dataclass(frozen=True)
class _Found:
    chat_id: str
    repo: str
    path: Path
    info: _Info
    modified: datetime
    # The Claude Code worktree the chat ran in, None for the repo folder.
    worktree: str | None


class ClaudeChats:
    def __init__(
        self,
        *,
        claude_dir: Path | None,
        repos: RepoService,
        store: SessionStore,
        archive: ChatArchive,
        bus: EventBus,
        live: LiveChats,
        interval: timedelta = POLL_INTERVAL,
        on_refresh: ChatsListener | None = None,
    ) -> None:
        self._on_refresh = on_refresh
        self._projects = None if claude_dir is None else claude_dir / "projects"
        self._repos = repos
        self._store = store
        self._archive = archive
        self._bus = bus
        self._live = live
        self._interval = interval
        self._cache: dict[Path, _Cached] = {}
        self._files: dict[str, Path] = {}
        self._signatures: dict[str, _Signature] = {}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    async def list_chats(
        self, repo: str | None = None, include_automated: bool = False
    ) -> list[ClaudeChat]:
        """Newest activity first; all registered repos, or one. Automated chats only on request."""
        if repo is not None:
            self._repos.get(repo)
        return [
            chat
            for chat in await self.refresh()
            if (repo is None or chat.repo == repo) and (include_automated or not chat.automated)
        ]

    async def get(self, chat_id: str) -> ClaudeChat:
        for chat in await self.refresh():
            if chat.id == chat_id:
                return chat
        msg = f"unknown Claude Code chat {chat_id!r}"
        raise ClaudeChatNotFoundError(msg)

    async def set_archived(self, chat_id: str, *, archived: bool) -> ClaudeChat:
        """Archive or restore the chat in harness; a change is announced like any other."""
        await self.get(chat_id)
        await self._archive.set(chat_id, archived=archived)
        return await self.get(chat_id)

    async def history(self, chat_id: str) -> list[Event]:
        """The transcript as harness session events, numbered from 1."""
        chat, transcript = await self._read(chat_id)
        return [
            Event(
                id=index,
                type=item.type,
                ts=item.ts or chat.created_at,
                session_id=chat.id,
                payload=item.payload,
            )
            for index, item in enumerate(transcript.history, start=1)
        ]

    async def importable(self, chat_id: str) -> ChatImport:
        """Everything a harness session needs to continue the chat."""
        chat, transcript = await self._read(chat_id)
        return ChatImport(
            repo=chat.repo,
            title=chat.title,
            prompt=transcript.first_prompt or chat.title,
            cwd=chat.cwd,
            provider_session_id=chat.id,
            history=[(item.type, item.payload) for item in transcript.history],
        )

    async def refresh(self) -> list[ClaudeChat]:
        """Scan again (only changed files are read) and announce repos whose list changed."""
        async with self._lock:
            repos = self._repos.list_repos()
            found = await asyncio.to_thread(self._scan, repos)
            owned = await self._store.provider_session_ids()
            running = await asyncio.to_thread(self._live.running)
            archived = await self._archive.archived_ids()
            newest: dict[str, _Found] = {}
            for item in found:
                if item.chat_id in owned:
                    continue
                kept = newest.get(item.chat_id)
                if kept is None or item.modified > kept.modified:
                    newest[item.chat_id] = item
            self._files = {chat_id: item.path for chat_id, item in newest.items()}
            chats = sorted(
                (
                    _chat(item, running=item.chat_id in running, archived=item.chat_id in archived)
                    for item in newest.values()
                ),
                key=lambda chat: (chat.last_activity_at, chat.id),
                reverse=True,
            )
            changed = self._note_changes(repos, chats)
            if self._on_refresh is not None:
                await self._on_refresh(chats)
        if changed:
            names: list[JsonValue] = [*changed]
            await self._bus.publish_ephemeral(types.CLAUDE_CHATS_UPDATED, {"repos": names})
        return chats

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _poll(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception:
                logger.exception("reading Claude Code chats failed")
            await asyncio.sleep(self._interval.total_seconds())

    async def _read(self, chat_id: str) -> tuple[ClaudeChat, Transcript]:
        chat = await self.get(chat_id)
        try:
            transcript = await asyncio.to_thread(read_transcript, self._files[chat_id])
        except OSError as error:
            msg = f"the Claude Code chat {chat_id!r} can no longer be read"
            raise ClaudeChatNotFoundError(msg) from error
        return chat, transcript

    def _note_changes(self, repos: list[RepoConfig], chats: list[ClaudeChat]) -> list[str]:
        signatures = {
            repo.name: tuple(
                (
                    c.id,
                    c.title,
                    c.last_activity_at,
                    c.message_count,
                    c.open_in_claude_code,
                    c.archived,
                )
                for c in chats
                if c.repo == repo.name
            )
            for repo in repos
        }
        changed = sorted(
            name
            for name, signature in signatures.items()
            if signature != self._signatures.get(name, ())
        )
        self._signatures = signatures
        return changed

    def _scan(self, repos: list[RepoConfig]) -> list[_Found]:
        if self._projects is None:
            return []
        found: list[_Found] = []
        seen: set[Path] = set()
        for repo in repos:
            root = _normal(repo.path)
            for directory in candidate_dirs(self._projects, repo.path):
                for file in sorted(directory.glob("*.jsonl")):
                    seen.add(file)
                    if not _SESSION_ID.fullmatch(file.stem):
                        continue
                    read = self._info(file)
                    if read is None or not _belongs(root, read[0].cwd):
                        continue
                    info, modified = read
                    worktree = None if info.cwd == root else info.cwd.name
                    found.append(_Found(file.stem, repo.name, file, info, modified, worktree))
        self._cache = {path: cached for path, cached in self._cache.items() if path in seen}
        return found

    def _info(self, file: Path) -> tuple[_Info, datetime] | None:
        """The file's info and change time; None if unreadable or not a usable chat."""
        try:
            stat = file.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            cached = self._cache.get(file)
            if cached is None or cached.stamp != stamp:
                cached = _Cached(stamp, _summary(read_transcript(file)))
                self._cache[file] = cached
        except OSError:
            return None
        if cached.info is None:
            return None
        return cached.info, datetime.fromtimestamp(stat.st_mtime, UTC)


def _summary(transcript: Transcript) -> _Info | None:
    """None for a chat without a cwd or without any title (no prompt yet)."""
    title = transcript.display_title
    if transcript.cwd is None or title is None:
        return None
    return _Info(
        title=title,
        cwd=_normal(transcript.cwd),
        created_at=transcript.created_at,
        message_count=transcript.message_count,
        entrypoint=transcript.entrypoint,
    )


def _belongs(root: Path, cwd: Path) -> bool:
    """The repo folder itself, or a Claude Code worktree in it that is not harness's."""
    return cwd == root or (
        cwd.parent == claude_worktrees_dir(root) and not cwd.name.startswith(WORKTREE_PREFIX)
    )


def _chat(item: _Found, *, running: bool, archived: bool) -> ClaudeChat:
    info = item.info
    return ClaudeChat(
        id=item.chat_id,
        repo=item.repo,
        title=info.title,
        cwd=info.cwd,
        worktree=item.worktree,
        created_at=info.created_at or item.modified,
        last_activity_at=item.modified,
        message_count=info.message_count,
        open_in_claude_code=running,
        entrypoint=info.entrypoint,
        automated=info.entrypoint is not None and info.entrypoint.startswith(AUTOMATED_PREFIX),
        archived=archived,
    )


def _normal(path: Path) -> Path:
    return Path(unicodedata.normalize("NFC", str(path)))
