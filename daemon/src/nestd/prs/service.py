"""Pull requests Nest opened: listing, reading now, and merging after the user
approves, which also closes a session that is not movable (D034, B119). The user can also
ask to merge once the checks pass (B149): GitHub's own auto-merge does it when GitHub waits
for required checks, and Nest merges by itself when the pull request becomes ready otherwise,
as GitHub merges at once a pull request whose checks are not required.

The daemon merges for the user's click; while the user has not let agents push, the git guard
keeps pixies and subagents from `gh pr merge` (D004, D160).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from weakref import WeakValueDictionary

from nestd.approvals.models import ApprovalKind
from nestd.approvals.queue import ApprovalQueue
from nestd.errors import ConflictError, NestError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.runner import CommandError, CommandRunner, GitError
from nestd.prs.ci_logs import feedback
from nestd.prs.errors import NoFailingChecksError, NoPullRequestError, PrReadError
from nestd.prs.github import repo_of
from nestd.prs.models import AutoMergeRequest, MergeRequest, PrListItem, PrState
from nestd.prs.monitor import PrMonitor, restacking
from nestd.review.errors import GitActionError
from nestd.sessions.errors import SessionBusyError
from nestd.sessions.manager import SessionManager
from nestd.sessions.models import IN_FLIGHT, SendResult, Session, SessionState
from nestd.sessions.store import SessionStore
from nestd.sessions.updates import announce_changes

logger = logging.getLogger(__name__)

type PrFilter = PrState | None


class PullRequests:
    def __init__(
        self,
        *,
        sessions: SessionManager,
        store: SessionStore,
        approvals: ApprovalQueue,
        monitor: PrMonitor,
        bus: EventBus,
        run: CommandRunner,
        cwd: Path,
    ) -> None:
        self._sessions = sessions
        self._store = store
        self._approvals = approvals
        self.monitor = monitor
        self._bus = bus
        self._run = run
        self._cwd = cwd
        # One operation per session at a time; a lock goes once nobody holds it (IMP-13).
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        monitor.listen(on_ready=self._merge_when_ready, on_merged=self._merged_elsewhere)
        self._stacked: Callable[[str], Awaitable[None]] | None = None

    def on_merged(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """Called with a session's id once its pull request merged (B149)."""
        self._stacked = callback

    async def list_prs(self, repo: str | None, state: PrFilter) -> list[PrListItem]:
        """Pull requests Nest opened, newest first; one not read yet counts as open."""
        items: list[PrListItem] = []
        for session in await self._store.with_prs(repo):
            current = "open" if session.pr is None else session.pr.state
            if state is not None and current != state:
                continue
            items.append(
                PrListItem(
                    session_id=session.id,
                    repo=session.repo,
                    session_title=session.title,
                    session_state=session.state,
                    url=session.pr_url or "",
                    summary=session.pr_summary,
                    pr=session.pr,
                )
            )
        return items

    async def refresh(self, session_id: str) -> Session:
        session = await self._sessions.get(session_id)
        _require_pr(session)
        return await self.monitor.refresh(session)

    async def send_ci_feedback(self, session_id: str) -> SendResult:
        """Read the pull request now and send its failing checks' logs to the agent as a
        message, which starts a turn or is queued like any other (IMP-08).
        """
        session = await self._sessions.get(session_id)
        url = _require_pr(session)
        session = await self.monitor.refresh(session)
        failing = [] if session.pr is None else session.pr.checks.items
        failing = [check for check in failing if check.state == "failure"]
        if not failing:
            raise NoFailingChecksError
        text = await feedback(self._run, self._cwd, failing, repo_of(url))
        return await self._sessions.send(session_id, text, [])

    async def send_review_feedback(
        self, session_id: str, ids: list[str] | None = None
    ) -> SendResult:
        """Read the pull request now and send the review comments that wait (those in
        `ids` only, when given) to the agent as a message, which starts a turn or is queued
        like any other (B101).
        """
        session = await self._sessions.get(session_id)
        _require_pr(session)
        await self.monitor.refresh(session)
        return await self.monitor.send_review(session_id, ids)

    async def set_review_auto_send(self, session_id: str, auto_send: bool) -> Session:
        """Whether new review comments go to the agent on their own; switched on, those
        that wait go at the next read, which comes at once (B101).
        """
        _require_pr(await self._sessions.get(session_id))
        session = await self.monitor.set_auto_send(session_id, auto_send)
        if auto_send:
            self.monitor.check_soon(session_id)
        return session

    async def set_auto_merge(self, session_id: str, request: AutoMergeRequest) -> Session:
        """Merge once the checks pass, or stop waiting. A pull request that is ready now is
        merged now. GitHub's auto-merge is turned on when GitHub waits for something itself
        (`blocked`), so the merge happens while this Mac sleeps too; when the repository does
        not allow it, Nest waits instead.
        """
        session = await self._sessions.get(session_id)
        url = _require_pr(session)
        pr = session.pr
        if pr is not None and pr.state != "open":
            msg = f"the pull request is already {pr.state}"
            raise NoPullRequestError(msg)
        choice = MergeRequest(method=request.method, delete_branch=request.delete_branch)
        if request.enabled and pr is not None and pr.ready_to_merge() and pr.auto_merge is None:
            return await self.merge(session_id, choice)
        if request.enabled and pr is not None and pr.merge_state == "blocked":
            await self._github_auto_merge(url, choice, pr.head_sha)
        if not request.enabled and pr is not None and pr.auto_merge is not None:
            argv = ["gh", "pr", "merge", url, "--repo", repo_of(url), "--disable-auto"]
            await self._gh(session, "auto_merge", argv)
        session = await self._store.set_quietly(
            session_id, merge_when_ready=choice if request.enabled else None
        )
        await announce_changes(self._bus, session, {"merge_when_ready"})
        try:
            return await self.monitor.refresh(session)
        except PrReadError:
            return session

    async def _github_auto_merge(self, url: str, choice: MergeRequest, head: str | None) -> None:
        """Turn on GitHub's auto-merge; a refusal, such as a repository that does not allow
        it, is only logged, as Nest then merges by itself.
        """
        argv = [*_merge_argv(url, choice, head), "--auto"]
        try:
            await self._run(argv, self._cwd)
        except (CommandError, OSError) as error:
            logger.info("GitHub's auto-merge is not on for %s (%s)", url, type(error).__name__)

    async def _merge_when_ready(self, session_id: str) -> None:
        """The pull request became ready and the user asked to merge it then. A merge that
        fails, such as while the agent works, leaves the usual merge approval.
        """
        session = await self._sessions.get(session_id)
        choice = session.merge_when_ready
        if choice is None:
            return
        try:
            await self.merge(session_id, choice)
        except NestError as error:
            logger.warning("could not merge %s when ready (%s)", session_id, type(error).__name__)
            await self.monitor.offer_merge(await self._sessions.get(session_id))

    async def _merged_elsewhere(self, session_id: str) -> None:
        if self._stacked is not None:
            await self._stacked(session_id)

    async def merge(self, session_id: str, request: MergeRequest) -> Session:
        """Merge with gh. A movable chat stays open with its worktree, which goes only when
        the user asks (B119); any other session closes and its worktree is removed. The
        branch stays (on GitHub too, unless the request asks gh to delete it).

        A failed merge changes nothing and can be retried; a merge that worked but whose
        worktree could not be removed leaves the session open to close again.
        """
        async with (
            self._locks.setdefault(session_id, asyncio.Lock()),
            self._sessions.publishing(session_id),
        ):
            session = await self._sessions.get(session_id)
            url = _require_pr(session)
            if session.pr is not None and session.pr.state != "open":
                msg = f"the pull request is already {session.pr.state}"
                raise NoPullRequestError(msg)
            if session.state in IN_FLIGHT or self._sessions.busy(session_id):
                msg = f"session {session_id!r} is working; wait until its turn ends"
                raise SessionBusyError(msg)
            if restacking(session):
                msg = "This chat's branch waits to move onto its new base: push it first."
                raise ConflictError(msg)
            await self._gh_merge(session, url, request)
            await self._bus.publish(
                types.PR_MERGED, {"url": url, "method": request.method}, session_id
            )
            review = await self._approvals.pending(session_id, ApprovalKind.MERGE)
            if review is not None:
                await self._approvals.resolve(
                    review.id, {"action": "merged", "method": request.method}
                )
            session = await self._merged_status(session)
            if session.state is SessionState.CLOSED or session.movable:
                return session
            try:
                return await self._sessions.close(
                    session_id, remove_worktree=session.worktree_path is not None
                )
            except GitError:
                logger.exception("merged %s but could not remove the worktree", url)
                return await self._sessions.get(session_id)

    async def _merged_status(self, session: Session) -> Session:
        """Read the state GitHub reports now (a merge queue keeps it open for a while)."""
        try:
            return await self.monitor.refresh(session)
        except PrReadError:
            if session.pr is None:
                return session
            merged = session.pr.model_copy(update={"state": "merged"})
            return await self.monitor.record(session, merged)

    async def _gh_merge(self, session: Session, url: str, request: MergeRequest) -> None:
        head = None if session.pr is None else session.pr.head_sha
        await self._gh(session, "merge", _merge_argv(url, request, head))

    async def _gh(self, session: Session, step: str, argv: list[str]) -> None:
        """Run gh; a failure is published as `git.failed` and raised."""
        try:
            await self._run(argv, self._cwd)
            return
        except CommandError as error:
            stderr = error.stderr
        except OSError as error:  # gh is not installed
            stderr = str(error)
        failure = GitActionError(step, stderr)
        await self._bus.publish(
            types.GIT_FAILED, {"step": step, "stderr": failure.stderr}, session.id
        )
        raise failure


def _merge_argv(url: str, request: MergeRequest, head: str | None) -> list[str]:
    # Outside any checkout and with --repo, gh deletes only the branch on GitHub; the local
    # one stays, as Nest deletes no branch (B96).
    argv = ["gh", "pr", "merge", url, "--repo", repo_of(url), f"--{request.method}"]
    if request.delete_branch:
        argv.append("--delete-branch")
    if head is not None:
        # Merge only what the checks ran on.
        argv += ["--match-head-commit", head]
    return argv


def _require_pr(session: Session) -> str:
    if session.pr_url is None:
        msg = f"session {session.id!r} has no pull request"
        raise NoPullRequestError(msg)
    return session.pr_url
