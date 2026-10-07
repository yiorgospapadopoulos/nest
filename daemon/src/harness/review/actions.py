"""Approve, reject or send feedback on a session's work.

Approving commits, pushes and opens a pull request with the daemon's credentials; the
pending review is resolved only when every step succeeded, so a failure can be retried.
"""

import asyncio

from pydantic import JsonValue

from harness.approvals.models import ApprovalKind
from harness.approvals.queue import ApprovalQueue
from harness.errors import ConflictError, InvalidInputError
from harness.prs.monitor import PrMonitor
from harness.prs.summary import pr_summary
from harness.repos.service import FALLBACK_BRANCH, RepoService
from harness.review.diffs import session_diff
from harness.review.errors import GitViolationError
from harness.review.models import ApproveRequest, SessionDiff
from harness.review.publish import GitPublisher, PublishPlan, PullRequest
from harness.sessions.errors import SessionBusyError
from harness.sessions.manager import SessionManager
from harness.sessions.models import IN_FLIGHT, Session
from harness.sessions.rules import require_cwd, require_open, require_workspace
from harness.tracking.service import Tracking


class ReviewActions:
    def __init__(
        self,
        *,
        sessions: SessionManager,
        repos: RepoService,
        approvals: ApprovalQueue,
        tracking: Tracking,
        publisher: GitPublisher,
        prs: PrMonitor,
    ) -> None:
        self._sessions = sessions
        self._repos = repos
        self._approvals = approvals
        self._tracking = tracking
        self._publisher = publisher
        self._prs = prs
        self._locks: dict[str, asyncio.Lock] = {}

    async def diff(self, session_id: str) -> SessionDiff:
        session = await self._sessions.get(session_id)
        await self._repos.require_git(session.repo)
        return await session_diff(require_workspace(session), session.base_ref)

    async def approve(self, session_id: str, request: ApproveRequest) -> Session:
        async with self._lock(session_id):
            session = await self._idle(session_id)
            require_workspace(session)
            await self._repos.require_git(session.repo)
            if session.git_violation and not request.acknowledge_violation:
                msg = (
                    "the agent changed git refs itself; check them and set "
                    "acknowledge_violation to publish anyway"
                )
                raise GitViolationError(msg)
            plan = await self._plan(session, request)
            try:
                session = await self._publisher.publish(session, plan)
            finally:
                await self._sessions.refresh_refs(session_id)
            if plan.push and session.pr_url is not None:
                # A new pull request, or new commits on one: read it without waiting.
                self._prs.check_soon(session_id)
            await self._resolve_review(
                session_id,
                {
                    "action": "approved",
                    "commit_sha": session.commit_sha,
                    "pushed": request.push,
                    "pr_url": session.pr_url,
                },
            )
            return session

    async def reject(self, session_id: str) -> Session:
        """Discard the work: close the session and remove its worktree and branch."""
        async with self._lock(session_id):
            require_open(await self._sessions.get(session_id))
            await self._resolve_review(session_id, {"action": "rejected"})
            return await self._sessions.close(session_id, remove_worktree=True)

    async def feedback(self, session_id: str, text: str) -> Session:
        """Send the user's note into the same session; that supersedes the review."""
        return await self._sessions.send(session_id, text, [])

    async def _idle(self, session_id: str) -> Session:
        session = await self._sessions.get(session_id)
        require_open(session)
        if session.state in IN_FLIGHT or self._sessions.busy(session_id):
            msg = f"session {session_id!r} is working; wait until its turn ends"
            raise SessionBusyError(msg)
        return session

    async def _plan(self, session: Session, request: ApproveRequest) -> PublishPlan:
        if request.open_pr and not request.push:
            msg = "opening a pull request needs push"
            raise InvalidInputError(msg)
        if session.mode == "in_place":
            if request.open_pr:
                msg = "in-place sessions push without a pull request; set open_pr to false"
                raise ConflictError(msg)
            paths = await self._chosen_paths(session, request.files)
            return PublishPlan(request.commit_message, paths, request.push, None)
        if request.files is not None:
            msg = "files applies to in-place sessions; a worktree session commits all its work"
            raise InvalidInputError(msg)
        pull_request = None
        if request.open_pr:
            pull_request = PullRequest(
                base=self._repos.get(session.repo).default_branch or FALLBACK_BRANCH,
                title=request.pr_title or session.title,
                body=request.pr_body or await self._default_body(session),
                summary=await self._pr_summary(session),
            )
        return PublishPlan(request.commit_message, None, request.push, pull_request)

    async def _chosen_paths(self, session: Session, files: list[str] | None) -> list[str]:
        if not files:
            msg = "in-place sessions commit only the files listed in files"
            raise InvalidInputError(msg)
        diff = await session_diff(require_cwd(session), session.base_ref)
        changed = {f.path: f for f in diff.files}
        unknown = sorted(set(files) - changed.keys())
        if unknown:
            msg = f"not changed in this session: {', '.join(unknown)}"
            raise InvalidInputError(msg)
        # A renamed file's old path goes with it, so the whole rename is committed.
        return sorted({path for f in files for path in (f, changed[f].old_path) if path})

    async def _pr_summary(self, session: Session) -> str:
        """The pending review's summary text and the whole work's diff stats."""
        review = await self._approvals.pending(session.id, ApprovalKind.REVIEW)
        text = None if review is None else review.payload.get("summary")
        if not isinstance(text, str):
            text = await self._tracking.summary(session.id)
        diff = await session_diff(require_cwd(session), session.base_ref)
        return pr_summary(text, diff.stats)

    async def _default_body(self, session: Session) -> str:
        summary = await self._tracking.summary(session.id)
        return f"{session.title}\n\n{summary}" if summary else session.title

    async def _resolve_review(self, session_id: str, resolution: dict[str, JsonValue]) -> None:
        review = await self._approvals.pending(session_id, ApprovalKind.REVIEW)
        if review is not None:
            await self._approvals.resolve(review.id, resolution)

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())
