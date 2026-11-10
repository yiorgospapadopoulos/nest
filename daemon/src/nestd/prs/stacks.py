"""Stacked pull requests (B149, D177): a chat whose branch starts from another chat's
branch opens its pull request into that branch, and moves onto the next base when the one
under it merges.

When a pull request merges, each chat stacked on it is rebased on the Mac by itself, onto
origin's copy of the branch it merged into, if the chat is idle and has no uncommitted
changes; a chat stacked on that one then moves onto its rebased branch, in order. Nothing
is pushed: a stacked chat with an open pull request waits in Needs you, and the user's click
force-pushes it (with a lease on what GitHub has) and points its pull request at the new
base. A rebase that cannot happen by itself, such as one that stops on conflicts, waits for
the same click, which tries it again.

Every git command runs with `HARDENED` overrides after the repository's config was checked,
and the push goes through the publisher's checks (D050).
"""

import asyncio
import logging
from pathlib import Path
from weakref import WeakValueDictionary

from pydantic import JsonValue

from nestd.approvals.models import ApprovalKind
from nestd.approvals.queue import ApprovalQueue
from nestd.errors import ConflictError, NestError
from nestd.events.bus import EventBus
from nestd.gitops.remotes import REMOTE
from nestd.gitops.runner import CommandError, CommandRunner
from nestd.gitops.safety import HARDENED
from nestd.prs.github import repo_of
from nestd.prs.models import Restack, Stack
from nestd.prs.monitor import RESTACKING, PrMonitor
from nestd.repos.service import FALLBACK_BRANCH, RepoService
from nestd.review.errors import BackgroundRunningError, GitActionError
from nestd.review.publish import GitPublisher
from nestd.sessions.errors import SessionBusyError
from nestd.sessions.manager import SessionManager
from nestd.sessions.models import IN_FLIGHT, Session, SessionState
from nestd.sessions.rules import require_cwd
from nestd.sessions.store import SessionStore
from nestd.sessions.updates import announce_changes

logger = logging.getLogger(__name__)


class RestackError(ConflictError):
    """The branch could not move onto its new base; the text says why, for the user."""

    code = "restack_failed"

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class Stacks:
    def __init__(
        self,
        *,
        store: SessionStore,
        sessions: SessionManager,
        approvals: ApprovalQueue,
        publisher: GitPublisher,
        repos: RepoService,
        monitor: PrMonitor,
        bus: EventBus,
        run: CommandRunner,
        neutral_cwd: Path,
    ) -> None:
        """`run` runs git and gh with the user's login; `neutral_cwd` is a folder outside
        any checkout, for gh.
        """
        self._store = store
        self._sessions = sessions
        self._approvals = approvals
        self._publisher = publisher
        self._repos = repos
        self._monitor = monitor
        self._bus = bus
        self._run = run
        self._neutral_cwd = neutral_cwd
        # One restack per session at a time; a lock goes once nobody holds it (IMP-13).
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    async def parent_merged(self, parent_id: str) -> None:
        """The session's pull request merged: the chats stacked on it move onto the branch
        it merged into, which stays their pull request's base while the session's own was
        stacked on it, and is otherwise the base of theirs too.
        """
        parent = await self._store.get(parent_id)
        pr = parent.pr
        if pr is None or pr.state != "merged":
            return
        base = pr.base_branch or self._default_branch(parent)
        under = parent.stack
        grandparent = under.parent if under is not None and under.parent_branch == base else None
        upstream = pr.head_sha or parent.commit_sha or parent.branch
        if upstream is None:
            return
        restack = Restack(
            upstream=upstream, onto=f"refs/remotes/{REMOTE}/{base}", fetch=base, base=base
        )
        stack = Stack(
            parent=grandparent,
            parent_branch=base if grandparent is not None else None,
            restack=restack,
        )
        for child in await self._store.stacked_on(parent_id):
            await self._move(child, stack)

    async def restack(self, session_id: str) -> Session:
        """The user's click: rebase now when that has not happened, then for an open pull
        request push the branch and point the pull request at the new base.
        """
        async with self._lock(session_id), self._sessions.publishing(session_id):
            session = await self._idle(session_id)
            stack = session.stack
            if stack is None or stack.restack is None:
                msg = "This chat's branch has nothing to move onto a new base."
                raise ConflictError(msg)
            await self._require_parent_pushed(stack)
            restack = stack.restack
            cwd = require_cwd(session)
            if restack.rebased is None or not await self._contains(cwd, restack.rebased):
                await self._require_clean(session)
                session = await self._rebase_or_record(session)
                restack = _restack_of(session)
            assert restack.rebased is not None  # noqa: S101 (set by the rebase)
            if _open_pr(session):
                await self._push(session, restack, restack.rebased)
            session = await self._done(session)
            self._monitor.check_soon(session_id)
            return session

    async def _move(self, session: Session, stack: Stack) -> None:
        """Record where the chat's branch goes, then rebase it by itself if it can."""
        async with self._lock(session.id):
            session = await self._set_stack(session, stack)
            await self._approvals.expire(session.id, (ApprovalKind.MERGE,), RESTACKING)
            try:
                if await self._busy(session):
                    msg = "The chat was working, so its branch was not moved by itself."
                    raise RestackError(msg)
                await self._require_clean(session)
                session = await self._rebase_or_record(session)
            except NestError as error:
                logger.info("stacked chat %s waits to be restacked (%s)", session.id, error)
                await self._ask(await self._record(await self._store.get(session.id), error))
                return
            if _open_pr(session):
                await self._ask(session)
            else:
                await self._done(session)

    async def _rebase_or_record(self, session: Session) -> Session:
        """Rebase, keeping why it failed with the chat's restack."""
        try:
            return await self._rebase(session)
        except NestError as error:
            await self._record(session, error)
            raise

    async def _record(self, session: Session, error: NestError) -> Session:
        restack = _restack_of(session).model_copy(update={"error": str(error)})
        return await self._set_stack(session, _with(session, restack))

    async def _rebase(self, session: Session) -> Session:
        """Move the chat's own commits onto the new base; then the chats stacked on it
        follow its rebased branch.
        """
        restack = _restack_of(session)
        cwd = require_cwd(session)
        await self._publisher.require_safe_config(session)
        if restack.fetch is not None:
            await self._check_branch(cwd, restack.fetch)
            refspec = f"+refs/heads/{restack.fetch}:refs/remotes/{REMOTE}/{restack.fetch}"
            await self._git(cwd, "fetch", "--no-tags", "--no-recurse-submodules", REMOTE, refspec)
        old_head = await self._rev(cwd, "HEAD")
        _require_on_pr(session, old_head)
        onto = await self._rev(cwd, f"{restack.onto}^{{commit}}")
        if not await self._contains(cwd, onto):
            fork = await self._fork_point(cwd, restack.upstream)
            try:
                await self._git(cwd, "rebase", "--no-autosquash", "--onto", onto, fork)
            except GitActionError:
                conflicts = await self._conflicts(cwd)
                await self._git(cwd, "rebase", "--abort")
                files = f": {', '.join(conflicts)}" if conflicts else ""
                msg = f"Rebasing onto {restack.base} stopped on conflicts{files}."
                raise RestackError(msg) from None
        new_head = await self._rev(cwd, "HEAD")
        rebased = restack.model_copy(update={"rebased": new_head, "error": None})
        session = await self._set_stack(session, _with(session, rebased), base_ref=onto)
        if session.branch is not None and new_head != old_head:
            follow = Restack(
                upstream=old_head, onto=f"refs/heads/{session.branch}", base=session.branch
            )
            for child in await self._store.stacked_on(session.id):
                await self._move(child, _with(child, follow))
        return session

    async def _push(self, session: Session, restack: Restack, sha: str) -> None:
        pr = session.pr
        url = session.pr_url
        assert url is not None  # noqa: S101 (an open pull request)
        if pr is None or pr.head_sha is None:
            msg = "Nest has not read what GitHub has on the branch yet; refresh and try again."
            raise ConflictError(msg)
        remote_url = self._repos.get(session.repo).remote_url
        await self._publisher.push_rebased(session, sha, pr.head_sha, remote_url)
        if pr.base_branch != restack.base:
            argv = ["gh", "pr", "edit", url, "--repo", repo_of(url), "--base", restack.base]
            try:
                await self._run(argv, self._neutral_cwd)
            except CommandError as error:
                raise GitActionError("pr", error.stderr) from None
            except OSError as error:  # gh is not installed
                raise GitActionError("pr", str(error)) from None

    async def _done(self, session: Session) -> Session:
        session = await self._set_stack(session, _with(session, None))
        ask = await self._approvals.pending(session.id, ApprovalKind.RESTACK)
        if ask is not None:
            await self._approvals.resolve(ask.id, {"action": "pushed"})
        return session

    async def _ask(self, session: Session) -> None:
        """One item in Needs you: push the rebased branch, or rebase it and push."""
        stack = session.stack
        if stack is None or stack.restack is None or session.state is SessionState.CLOSED:
            return
        restack = stack.restack
        payload: dict[str, JsonValue] = {
            "branch": session.branch,
            "base": restack.base,
            "rebased": restack.rebased is not None,
            "error": restack.error,
            "number": None if session.pr is None else session.pr.number,
            "url": session.pr_url,
        }
        if restack.rebased is not None:
            text = f"{session.branch} moved onto {restack.base}; push it"
        else:
            text = f"Move {session.branch} onto {restack.base}"
        await self._approvals.add(session.id, ApprovalKind.RESTACK, payload, text)

    async def _require_parent_pushed(self, stack: Stack) -> None:
        if stack.parent is None:
            return
        parent = await self._store.get(stack.parent)
        if parent.stack is not None and parent.stack.restack is not None:
            msg = f"Move the branch of “{parent.title}”, under this one, first."
            raise ConflictError(msg)

    async def _idle(self, session_id: str) -> Session:
        session = await self._store.get(session_id)
        if await self._busy(session):
            msg = f"session {session_id!r} is working; wait until its turn ends"
            raise SessionBusyError(msg)
        if self._sessions.background_running(session_id):
            raise BackgroundRunningError
        return session

    async def _busy(self, session: Session) -> bool:
        return (
            session.state in IN_FLIGHT
            or self._sessions.busy(session.id)
            or self._sessions.background_running(session.id)
        )

    async def _require_clean(self, session: Session) -> None:
        """Only committed work moves: uncommitted changes, or a checkout that is not on the
        chat's branch, keep the branch where it is.
        """
        cwd = require_cwd(session)
        try:
            head = (await self._run(_git("symbolic-ref", "-q", "HEAD"), cwd)).strip()
        except CommandError:
            head = ""
        if session.branch is None or head != f"refs/heads/{session.branch}":
            msg = "The chat's folder is not on its branch, so the branch was not moved."
            raise RestackError(msg)
        changes = await self._git(cwd, "status", "--porcelain", "--untracked-files=no")
        if changes.strip():
            msg = "The chat has uncommitted changes, so its branch was not moved."
            raise RestackError(msg)

    async def _fork_point(self, cwd: Path, upstream: str) -> str:
        """Where the chat's own commits start: after the newest commit it shares with what
        was under it.
        """
        try:
            return (await self._git(cwd, "merge-base", "HEAD", upstream)).strip()
        except GitActionError:
            msg = "Nest could not find where this chat's own commits start."
            raise RestackError(msg) from None

    async def _contains(self, cwd: Path, sha: str) -> bool:
        try:
            await self._run(_git("merge-base", "--is-ancestor", sha, "HEAD"), cwd)
        except CommandError:
            return False
        return True

    async def _conflicts(self, cwd: Path) -> list[str]:
        try:
            listing = await self._git(cwd, "diff", "--name-only", "--diff-filter=U")
        except GitActionError:
            return []
        return sorted(line for line in listing.splitlines() if line)

    async def _check_branch(self, cwd: Path, branch: str) -> None:
        try:
            await self._run(_git("check-ref-format", "--branch", branch), cwd)
        except CommandError:
            msg = f"{branch!r} is not a branch name Nest fetches."
            raise RestackError(msg) from None
        if branch.startswith("-"):
            msg = f"{branch!r} is not a branch name Nest fetches."
            raise RestackError(msg)

    async def _rev(self, cwd: Path, ref: str) -> str:
        return (await self._git(cwd, "rev-parse", "--verify", "--end-of-options", ref)).strip()

    async def _git(self, cwd: Path, *args: str) -> str:
        try:
            return await self._run(_git(*args), cwd)
        except CommandError as error:
            raise GitActionError(args[0], error.stderr) from None
        except OSError as error:
            raise GitActionError(args[0], str(error)) from None

    async def _set_stack(
        self, session: Session, stack: Stack, base_ref: str | None = None
    ) -> Session:
        changes: dict[str, object] = {"stack": stack}
        if base_ref is not None:
            changes["base_ref"] = base_ref
        session = await self._store.set_quietly(session.id, **changes)
        await announce_changes(self._bus, session, set(changes))
        return session

    def _default_branch(self, session: Session) -> str:
        return self._repos.get(session.repo).default_branch or FALLBACK_BRANCH

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())


def _restack_of(session: Session) -> Restack:
    stack = session.stack
    assert stack is not None  # noqa: S101 (a chat with a restack)
    assert stack.restack is not None  # noqa: S101
    return stack.restack


def _with(session: Session, restack: Restack | None) -> Stack:
    stack = session.stack or Stack(parent=None, parent_branch=None)
    return stack.model_copy(update={"restack": restack})


def _require_on_pr(session: Session, head: str) -> None:
    """A branch with an open pull request moves only with what that pull request has, as
    Nest last read it: the click force-pushes the result, so commits made on the Mac since
    would go out unseen (B159 P-3).
    """
    if not _open_pr(session):
        return
    pr = session.pr
    if pr is None or pr.head_sha is None:
        msg = "Nest has not read what GitHub has on the branch yet; refresh and try again."
        raise RestackError(msg)
    if head != pr.head_sha:
        msg = (
            "The chat's branch is not where its pull request is on GitHub, so Nest did not "
            "move it. Push or drop its new commits, or pull the pull request's, then try again."
        )
        raise RestackError(msg)


def _open_pr(session: Session) -> bool:
    return session.pr_url is not None and (session.pr is None or session.pr.state == "open")


def _git(*args: str) -> list[str]:
    return ["git", *HARDENED, *args]
