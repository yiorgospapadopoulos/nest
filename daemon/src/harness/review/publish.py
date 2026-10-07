"""Commit, push and open a pull request with the daemon's own git and gh setup (D004).

Each step is announced as an event; a failure publishes `git.failed` and stops. A retry
skips what is done: nothing is committed twice, pushing again is harmless, and a pull
request is opened once.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from harness.events import types
from harness.events.bus import EventBus
from harness.gitops.runner import CommandError, CommandRunner
from harness.review.errors import GitActionError, NothingToCommitError
from harness.sessions.models import Session
from harness.sessions.rules import require_cwd
from harness.sessions.store import SessionStore

REMOTE = "origin"


@dataclass(frozen=True)
class PullRequest:
    base: str
    title: str
    body: str
    # Up to three lines kept on the session for dashboards (D034).
    summary: str


@dataclass(frozen=True)
class PublishPlan:
    message: str
    # Paths to commit; None commits every change (a worktree holds only the session's work).
    paths: list[str] | None
    push: bool
    pull_request: PullRequest | None


class GitPublisher:
    def __init__(self, run: CommandRunner, store: SessionStore, bus: EventBus) -> None:
        self._run = run
        self._store = store
        self._bus = bus

    async def publish(self, session: Session, plan: PublishPlan) -> Session:
        cwd = require_cwd(session)
        session = await self._commit(session, cwd, plan)
        if not plan.push:
            return session
        branch = await self._branch(session, cwd)
        await self._step(session, "push", ["git", "push", "-u", REMOTE, branch], cwd)
        await self._bus.publish(types.GIT_PUSHED, {"remote": REMOTE, "branch": branch}, session.id)
        if plan.pull_request is None or session.pr_url is not None:
            return session
        pr = plan.pull_request
        output = await self._step(
            session,
            "pr",
            [
                *("gh", "pr", "create", "--base", pr.base, "--head", branch),
                *("--title", pr.title, "--body", pr.body),
            ],
            cwd,
        )
        url = output.strip().splitlines()[-1]
        session = await self._store.update(session.id, pr_url=url, pr_summary=pr.summary)
        await self._bus.publish(types.PR_OPENED, {"url": url}, session.id)
        return session

    async def _branch(self, session: Session, cwd: Path) -> str:
        """The worktree's branch, or the checkout's current branch for in-place sessions."""
        if session.branch is not None:
            return session.branch
        argv = ["git", "symbolic-ref", "--short", "HEAD"]
        return (await self._step(session, "push", argv, cwd)).strip()

    async def _commit(self, session: Session, cwd: Path, plan: PublishPlan) -> Session:
        # With paths, `git commit -- <paths>` leaves anything else the user staged alone.
        paths = [] if plan.paths is None else ["--", *plan.paths]
        await self._stage(session, cwd, plan.paths)
        staged = await self._step(
            session, "commit", ["git", "diff", "--cached", "--name-only", *paths], cwd
        )
        if staged.strip():
            await self._step(
                session, "commit", ["git", "commit", "-q", "-m", plan.message, *paths], cwd
            )
            sha = await self._head(session, cwd)
            session = await self._store.update(session.id, commit_sha=sha)
            await self._bus.publish(types.GIT_COMMITTED, {"sha": sha}, session.id)
            return session
        if session.commit_sha is not None:
            return session  # committed by an earlier attempt
        head = await self._head(session, cwd)
        if head == session.base_ref:
            msg = "there are no changes to commit"
            raise NothingToCommitError(msg)
        # Commits the agent made itself, which the user chose to publish (D013 layer 4).
        return await self._store.update(session.id, commit_sha=head)

    async def _stage(self, session: Session, cwd: Path, paths: list[str] | None) -> None:
        if paths is None:
            await self._step(session, "commit", ["git", "add", "-A"], cwd)
            return
        # `git add` rejects paths git no longer knows, such as the old name of a file the
        # agent renamed with `git mv`; those changes are staged already.
        listed = await self._step(
            session,
            "commit",
            [
                *("git", "ls-files", "-z", "--cached", "--others", "--deleted"),
                *("--exclude-standard", "--", *paths),
            ],
            cwd,
        )
        known = sorted(set(filter(None, listed.split("\0"))))
        if known:
            await self._step(session, "commit", ["git", "add", "-A", "--", *known], cwd)

    async def _head(self, session: Session, cwd: Path) -> str:
        return (await self._step(session, "commit", ["git", "rev-parse", "HEAD"], cwd)).strip()

    async def _step(self, session: Session, step: str, argv: Sequence[str], cwd: Path) -> str:
        try:
            return await self._run(argv, cwd)
        except CommandError as error:
            stderr = error.stderr
        except OSError as error:  # the tool is not installed
            stderr = str(error)
        await self._bus.publish(types.GIT_FAILED, {"step": step, "stderr": stderr}, session.id)
        raise GitActionError(step, stderr)
