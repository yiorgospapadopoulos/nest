"""The Codex chats of the registered repos, read through a short-lived app-server (B113).

A repo's chats are those Codex ran in the repo folder or in one of its git worktrees (Codex
app worktrees and Claude Code's included), not in subfolders. Left out: sub-agent threads,
ephemeral ones, ones without a prompt yet, chats Nest owns (by thread id) and chats in
Nest's own worktrees. Archived chats stay listed, marked: the archive is Codex's own.

Asking Codex scans its rollout files, so it is asked only when they change (their names,
sizes and times), when the repos' folders change, after Nest archives a chat, or every few
minutes. Between those the last list is used; a failing app-server keeps it.
"""

import asyncio
import logging
import os
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from nestd.claude_sessions.errors import ClaudeChatNotFoundError
from nestd.claude_sessions.models import ClaudeChat
from nestd.claude_sessions.transcript import HistoryItem
from nestd.clock import Clock
from nestd.codex_chats.history import first_prompt, message_count, thread_history
from nestd.codex_chats.threads import CodexThread, archive_thread, list_threads, read_turns
from nestd.config.models import RepoConfig
from nestd.errors import NestError
from nestd.providers.codex_engine import CodexFetchError, ask_codex
from nestd.providers.codex_process import CodexLaunch, TransportFactory
from nestd.providers.codex_rpc import CodexRpc
from nestd.sessions.models import ChatImport
from nestd.sessions.titles import short_title
from nestd.worktrees.manager import OWNED_WORKTREE_PREFIXES

logger = logging.getLogger(__name__)

REREAD_AFTER = timedelta(minutes=5)
# Sources of chats the user typed in; any other is a program's.
_TYPED = frozenset({"cli", "vscode"})
# Codex's originator for the threads Nest starts.
NEST_ORIGINATOR = "nest"
_ROLLOUT_DIRS = ("sessions", "archived_sessions")

type _Stamp = tuple[tuple[str, int, int], ...]


class CodexChatsError(NestError):
    """Codex could not be asked; the message names only the kind of failure."""

    status_code = 502


@dataclass(frozen=True)
class _Folders:
    """A repo's folder and its git worktrees, by their real paths."""

    repo: str
    root: Path
    worktrees: frozenset[Path]


@dataclass(frozen=True)
class _Read:
    stamp: _Stamp
    folders: tuple[_Folders, ...]
    at: datetime


class CodexChats:
    def __init__(
        self,
        *,
        codex_home: Path | None,
        transport: TransportFactory,
        launch: Callable[[], CodexLaunch],
        clock: Clock,
        reread_after: timedelta = REREAD_AFTER,
    ) -> None:
        """No `codex_home` (as in tests) means no Codex chats at all."""
        self._home = codex_home
        self._transport = transport
        self._launch = launch
        self._clock = clock
        self._reread_after = reread_after
        self._threads: dict[str, CodexThread] = {}
        # Message counts by thread id, for the thread's last change.
        self._counts: dict[str, tuple[datetime, int]] = {}
        self._last: _Read | None = None
        self._failing = False
        self._lock = asyncio.Lock()

    async def chats(self, repos: list[RepoConfig], owned: set[str]) -> list[ClaudeChat]:
        """The Codex chats of `repos`, `owned` thread ids left out."""
        if self._home is None:
            return []
        async with self._lock:
            home = self._home
            stamp = await asyncio.to_thread(_stamp, home)
            folders = await asyncio.to_thread(_repo_folders, repos)
            if self._stale(stamp, folders):
                await self._reread(folders, owned)
                self._last = _Read(stamp, folders, self._clock.now())
            return await asyncio.to_thread(self._chats, folders, owned)

    async def set_archived(self, chat_id: str, *, archived: bool) -> None:
        """Archive or restore the chat in Codex; repeating it asks nothing."""
        thread = self._thread(chat_id)
        if thread.archived == archived:
            return

        async def ask(rpc: CodexRpc) -> None:
            await archive_thread(rpc, chat_id, archived=archived)

        await self._ask(ask)
        self._last = None

    async def history(self, chat: ClaudeChat) -> list[HistoryItem]:
        self._thread(chat.id)

        async def ask(rpc: CodexRpc) -> list[HistoryItem]:
            return thread_history(await read_turns(rpc, chat.id))

        return await self._ask(ask)

    async def importable(self, chat: ClaudeChat) -> ChatImport:
        """The chat to continue in Nest, restored in Codex first: it resumes no archived thread."""
        thread = self._thread(chat.id)
        await self.set_archived(chat.id, archived=False)
        history = await self.history(chat)
        return ChatImport(
            repo=chat.repo,
            title=chat.title,
            prompt=first_prompt(history) or chat.title,
            cwd=chat.cwd,
            provider_session_id=chat.id,
            history=[(item.type, item.payload) for item in history],
            provider="codex",
            model=thread.model,
        )

    def _thread(self, chat_id: str) -> CodexThread:
        thread = self._threads.get(chat_id)
        if thread is None:
            msg = f"unknown Codex chat {chat_id!r}"
            raise ClaudeChatNotFoundError(msg)
        return thread

    def _stale(self, stamp: _Stamp, folders: tuple[_Folders, ...]) -> bool:
        last = self._last
        return (
            last is None
            or last.stamp != stamp
            or last.folders != folders
            or self._clock.now() - last.at >= self._reread_after
        )

    async def _reread(self, folders: tuple[_Folders, ...], owned: set[str]) -> None:
        """The thread list, and the message counts of the repos' threads that changed.

        Both are kept as they are read, so a read cut off by the time limit (many chats
        counted at once) goes on from there the next time. A chat is listed once counted.
        """

        async def ask(rpc: CodexRpc) -> None:
            threads = await list_threads(rpc)
            self._threads = {thread.id: thread for thread in threads}
            self._counts = {
                thread_id: count
                for thread_id, count in self._counts.items()
                if thread_id in self._threads
            }
            places = await asyncio.to_thread(
                lambda: {thread.id: _place(thread.cwd, folders) for thread in threads}
            )
            for thread in threads:
                if not _listable(thread, owned) or places[thread.id] is None:
                    continue
                known = self._counts.get(thread.id)
                if known is None or known[0] != thread.updated_at:
                    history = thread_history(await read_turns(rpc, thread.id))
                    self._counts[thread.id] = (thread.updated_at, message_count(history))

        try:
            await self._ask(ask)
        except CodexChatsError as error:
            if not self._failing:
                logger.warning("reading Codex chats failed (%s)", error)
            self._failing = True
            return
        self._failing = False

    async def _ask[T](self, ask: Callable[[CodexRpc], Awaitable[T]]) -> T:
        try:
            return await ask_codex(self._transport, self._launch(), ask)
        except CodexFetchError as error:
            msg = f"Codex could not be asked ({error})"
            raise CodexChatsError(msg) from error

    def _chats(self, folders: tuple[_Folders, ...], owned: set[str]) -> list[ClaudeChat]:
        chats: list[ClaudeChat] = []
        for thread in self._threads.values():
            if not _listable(thread, owned):
                continue
            place = _place(thread.cwd, folders)
            count = self._counts.get(thread.id)
            if place is None or count is None:
                continue
            repo, worktree = place
            chats.append(
                ClaudeChat(
                    id=thread.id,
                    repo=repo,
                    title=thread.name or short_title(thread.preview),
                    cwd=thread.cwd,
                    worktree=worktree,
                    created_at=thread.created_at,
                    last_activity_at=thread.updated_at,
                    message_count=count[1],
                    open_in_claude_code=False,
                    entrypoint=thread.source,
                    automated=thread.source not in _TYPED or thread.originator == NEST_ORIGINATOR,
                    archived=thread.archived,
                    engine="codex",
                )
            )
        return chats


def _listable(thread: CodexThread, owned: set[str]) -> bool:
    return not (
        thread.parent is not None
        or thread.source == "subagent"
        or thread.ephemeral
        or not (thread.name or thread.preview)
        or thread.id in owned
    )


def _place(cwd: Path, folders: tuple[_Folders, ...]) -> tuple[str, str | None] | None:
    """The repo the folder belongs to and its worktree's name (None for the repo folder)."""
    real = _real(cwd)
    for entry in folders:
        if real == entry.root:
            return entry.repo, None
        if real in entry.worktrees:
            return entry.repo, real.name
    return None


def _repo_folders(repos: list[RepoConfig]) -> tuple[_Folders, ...]:
    return tuple(
        _Folders(repo.name, root, _git_worktrees(root))
        for repo in repos
        for root in (_real(repo.path),)
    )


def _git_worktrees(root: Path) -> frozenset[Path]:
    """The repo's git worktrees from `.git/worktrees/*/gitdir`, Nest's own left out."""
    found: set[Path] = set()
    try:
        entries = list(os.scandir(root / ".git" / "worktrees"))
    except OSError:
        return frozenset()
    for entry in entries:
        try:
            gitdir = Path(entry.path, "gitdir").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not gitdir:
            continue
        folder = _real(Path(gitdir).parent)
        if not folder.name.startswith(OWNED_WORKTREE_PREFIXES):
            found.add(folder)
    return frozenset(found)


def _stamp(home: Path) -> _Stamp:
    """The names, sizes and change times of Codex's rollout files."""
    found: list[tuple[str, int, int]] = []
    pending = [home / name for name in _ROLLOUT_DIRS]
    while pending:
        try:
            entries = list(os.scandir(pending.pop()))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.name.endswith(".jsonl"):
                    stat = entry.stat()
                    found.append((entry.path, stat.st_size, stat.st_mtime_ns))
            except OSError:
                continue
    return tuple(sorted(found))


def _real(path: Path) -> Path:
    return Path(unicodedata.normalize("NFC", os.path.realpath(path)))
