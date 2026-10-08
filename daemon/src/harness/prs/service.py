"""Pull requests harness opened: listing, reading now, and merging after the user
approves, which also closes the session (D034).

Only the daemon merges: agents stay blocked from `gh pr merge` by the git guard (D004).
"""

import asyncio
import logging
from pathlib import Path

from harness.approvals.models import ApprovalKind
from harness.approvals.queue import ApprovalQueue
from harness.events import types
from harness.events.bus import EventBus
from harness.gitops.runner import CommandError, CommandRunner, GitError
from harness.prs.errors import NoPullRequestError, PrReadError
from harness.prs.github import repo_of
from harness.prs.models import MergeRequest, PrListItem, PrState
from harness.prs.monitor import PrMonitor
from harness.review.errors import GitActionError
from harness.sessions.errors import SessionBusyError
from harness.sessions.manager import SessionManager
from harness.sessions.models import IN_FLIGHT, Session, SessionState
from harness.sessions.store import SessionStore

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
        self._locks: dict[str, asyncio.Lock] = {}

    async def list_prs(self, repo: str | None, state: PrFilter) -> list[PrListItem]:
        """Pull requests harness opened, newest first; one not read yet counts as open."""
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

    async def merge(self, session_id: str, request: MergeRequest) -> Session:
        """Merge with gh, then close the session and remove its worktree and branch.

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
            if session.state is SessionState.CLOSED:
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
        # Outside any checkout and with --repo, gh deletes only the remote branch; the
        # worktree removal deletes the local one (gh cannot switch a worktree's branch).
        argv = ["gh", "pr", "merge", url, "--repo", repo_of(url), f"--{request.method}"]
        if request.delete_branch:
            argv.append("--delete-branch")
        head = None if session.pr is None else session.pr.head_sha
        if head is not None:
            # Merge only what the checks ran on.
            argv += ["--match-head-commit", head]
        try:
            await self._run(argv, self._cwd)
            return
        except CommandError as error:
            stderr = error.stderr
        except OSError as error:  # gh is not installed
            stderr = str(error)
        failure = GitActionError("merge", stderr)
        await self._bus.publish(
            types.GIT_FAILED, {"step": "merge", "stderr": failure.stderr}, session.id
        )
        raise failure


def _require_pr(session: Session) -> str:
    if session.pr_url is None:
        msg = f"session {session.id!r} has no pull request"
        raise NoPullRequestError(msg)
    return session.pr_url
