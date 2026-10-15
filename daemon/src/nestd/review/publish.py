"""Commit, push and open a pull request with the daemon's own git and gh setup (D004).

Each step is announced as an event; a failure publishes `git.failed` and stops. A retry
skips what is done: nothing is committed twice, pushing again is harmless, and a pull
request is opened once.

The tree and its git config may hold what the agent planted, so (D050): every git command
runs with `HARDENED` overrides (no hooks, no fsmonitor program), nothing starts while the
repository's own config sets something that runs a program or sends data elsewhere, and a
push goes only to the origin URL the user confirmed. Both checks run again right before
the push, since a process the agent left running could change the config meanwhile
(SEC-07). The push sends Nest's commit, or the checked HEAD, by SHA in an explicit
refspec, without tags, so a commit slipped onto the branch is never pushed, and only to a
plain branch name: the agent can name a branch `--mirror` and check it out (SEC-01,
SEC-15). Nest's commit must sit on the HEAD approve checked (SEC-15). A worktree is
pushed only from its own branch (SEC-06), a git repository inside the work is never
committed (BUG-65), and staging switches off the filters nested repositories' own config
names (SEC-08). gh opens the pull request from a folder outside the checkout when it is
told the repository, so it reads nothing the agent wrote (SEC-17).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.hardened import nested_filter_overrides
from nestd.gitops.remotes import REMOTE, github_repo, push_urls
from nestd.gitops.runner import CommandError, CommandRunner
from nestd.gitops.safety import GIT_CONFIG_LIST, HARDENED, repo_settings, unsafe_settings
from nestd.review.errors import (
    GitActionError,
    HeadChangedError,
    NestedRepositoryError,
    NothingToCommitError,
    RemoteChangedError,
    RemoteNotConfirmedError,
    UnsafeBranchError,
    UnsafeRepoConfigError,
)
from nestd.sessions.models import Session
from nestd.sessions.rules import require_cwd
from nestd.sessions.store import SessionStore


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
    # HEAD's commit as approve's checks saw it; None in a repository without commits.
    head: str | None
    # Paths to commit; None commits every change (a worktree holds only the session's work).
    paths: list[str] | None
    push: bool
    pull_request: PullRequest | None
    # The push URL of origin that the user confirmed; a push needs it to match (D050).
    remote_url: str | None = None


class GitPublisher:
    def __init__(
        self, run: CommandRunner, store: SessionStore, bus: EventBus, neutral_cwd: Path
    ) -> None:
        self._run = run
        self._store = store
        self._bus = bus
        # A folder outside any checkout, for gh when it is told the repository.
        self._neutral_cwd = neutral_cwd

    async def publish(self, session: Session, plan: PublishPlan) -> Session:
        # Refused, in this order (409, after approve's own checks): the repository's config
        # (`unsafe_repo_config`); for a push, origin's URL (`remote_not_confirmed`,
        # `remote_changed`) and the branch (`unsafe_branch`); an untracked nested repository
        # (`nested_repository`); Nest's commit not on the checked HEAD (`head_changed`);
        # then, before the push, the config and origin's URL again. A git or gh failure is
        # a 502 with its step.
        cwd = require_cwd(session)
        await self.require_safe_config(session)
        branch = None
        if plan.push:
            await self.require_remote(session, plan.remote_url)
            branch = await self._branch(session, cwd)
        session, sha = await self._commit(session, cwd, plan)
        if branch is None:
            return session
        await self.require_safe_config(session)
        await self.require_remote(session, plan.remote_url)
        push = [
            *("push", "--no-verify", "--recurse-submodules=no", "--no-follow-tags"),
            *(REMOTE, f"{sha}:refs/heads/{branch}"),
        ]
        await self._step(session, "push", _git(*push), cwd)
        await self._track(session, cwd, branch)
        await self._bus.publish(types.GIT_PUSHED, {"remote": REMOTE, "branch": branch}, session.id)
        if plan.pull_request is None or session.pr_url is not None:
            return session
        pr = plan.pull_request
        # The confirmed remote names the repository, not gh's own pick among the remotes.
        repo = None if plan.remote_url is None else github_repo(plan.remote_url)
        output = await self._step(
            session,
            "pr",
            [
                *("gh", "pr", "create", *(() if repo is None else ("--repo", repo))),
                *("--base", pr.base, "--head", branch, "--title", pr.title, "--body", pr.body),
            ],
            cwd if repo is None else self._neutral_cwd,
        )
        url = output.strip().splitlines()[-1]
        session = await self._store.update(session.id, pr_url=url, pr_summary=pr.summary)
        await self._bus.publish(types.PR_OPENED, {"url": url}, session.id)
        return session

    async def require_safe_config(self, session: Session) -> None:
        """Refuse while the repository's own config would run a program (D050)."""
        cwd = require_cwd(session)
        listing = await self._step(session, "commit", _git(*GIT_CONFIG_LIST[1:]), cwd)
        unsafe = unsafe_settings(repo_settings(listing))
        if unsafe:
            await self._refuse(session, "commit", UnsafeRepoConfigError(unsafe))

    async def require_remote(self, session: Session, confirmed_url: str | None) -> None:
        """Refuse unless origin pushes to the confirmed URL, and only there (D050)."""
        current = await push_urls(require_cwd(session), self._run)
        if confirmed_url is None:
            await self._refuse(session, "push", RemoteNotConfirmedError(current))
        elif current != [confirmed_url]:
            await self._refuse(session, "push", RemoteChangedError(current, confirmed_url))

    async def _refuse(self, session: Session, step: str, error: Exception) -> NoReturn:
        await self._bus.publish(types.GIT_FAILED, {"step": step, "stderr": str(error)}, session.id)
        raise error

    async def _branch(self, session: Session, cwd: Path) -> str:
        """The checkout's current branch, which must be a plain branch name, and for a
        worktree its session's branch.
        """
        head = (await self._step(session, "push", _git("symbolic-ref", "HEAD"), cwd)).strip()
        branch = head.removeprefix("refs/heads/")
        if session.branch is not None and branch != session.branch:
            await self._refuse(session, "push", UnsafeBranchError(branch, session.branch))
        if branch == head or branch.startswith("-"):
            await self._refuse(session, "push", UnsafeBranchError(branch))
        try:
            await self._run(_git("check-ref-format", "--branch", branch), cwd)
        except CommandError:
            await self._refuse(session, "push", UnsafeBranchError(branch))
        return branch

    async def _commit(self, session: Session, cwd: Path, plan: PublishPlan) -> tuple[Session, str]:
        """Commit what is staged; the session and the commit a push sends."""
        # With paths, `git commit -- <paths>` leaves anything else the user staged alone.
        paths = [] if plan.paths is None else ["--", *plan.paths]
        await self._stage(session, cwd, plan.paths)
        staged = await self._step(
            session, "commit", _git("diff", "--cached", "--name-only", *paths), cwd
        )
        if staged.strip():
            commit = _git("commit", "-q", "--no-verify", "-m", plan.message, *paths)
            await self._step(session, "commit", commit, cwd)
            sha = await self._head(session, cwd)
            await self._require_parent(session, cwd, sha, plan.head)
            session = await self._store.update(session.id, commit_sha=sha)
            await self._bus.publish(types.GIT_COMMITTED, {"sha": sha}, session.id)
            return session, sha
        if plan.head is None or plan.head != session.commit_sha:
            msg = "there are no changes to commit"
            raise NothingToCommitError(msg)
        # Committed by an earlier attempt, whose push failed.
        return session, plan.head

    async def _require_parent(
        self, session: Session, cwd: Path, sha: str, head: str | None
    ) -> None:
        """Refuse a commit that does not sit on the checked HEAD: something committed
        between the checks and Nest's commit (SEC-15). The raw object is read, so no
        graft or replace ref can change its parents.
        """
        raw = await self._step(session, "commit", _git("cat-file", "commit", sha), cwd)
        headers = raw.split("\n\n", 1)[0].splitlines()
        parents = [line.removeprefix("parent ") for line in headers if line.startswith("parent ")]
        if parents != ([] if head is None else [head]):
            await self._refuse(session, "commit", HeadChangedError())

    async def _track(self, session: Session, cwd: Path, branch: str) -> None:
        """Record origin's branch as the upstream, as `push -u` does for a pushed branch
        name but not for a pushed SHA.
        """
        for key, value in (("remote", REMOTE), ("merge", f"refs/heads/{branch}")):
            config = _git("config", f"branch.{branch}.{key}", value)
            await self._step(session, "push", config, cwd)

    async def _stage(self, session: Session, cwd: Path, paths: list[str] | None) -> None:
        try:
            overrides = await nested_filter_overrides(cwd, self._run)
        except CommandError as error:
            raise await self._failure(session, "commit", error.stderr) from None
        # git lists an untracked repository inside the work as its folder, `lib/`.
        listing = ("ls-files", "-z", "--others", "--exclude-standard")
        if paths is None:
            untracked = await self._step(session, "commit", _git(*listing), cwd)
            await self._refuse_nested(session, untracked)
            await self._step(session, "commit", _git(*overrides, "add", "-A"), cwd)
            return
        # `git add` rejects paths git no longer knows, such as the old name of a file the
        # agent renamed with `git mv`; those changes are staged already.
        listed = await self._step(
            session, "commit", _git(*listing, "--cached", "--deleted", "--", *paths), cwd
        )
        await self._refuse_nested(session, listed)
        known = sorted(set(filter(None, listed.split("\0"))))
        if known:
            add = _git(*overrides, "add", "-A", "--", *known)
            await self._step(session, "commit", add, cwd)

    async def _refuse_nested(self, session: Session, listing: str) -> None:
        nested = sorted({path for path in listing.split("\0") if path.endswith("/")})
        if nested:
            await self._refuse(session, "commit", NestedRepositoryError(nested))

    async def _head(self, session: Session, cwd: Path) -> str:
        return (await self._step(session, "commit", _git("rev-parse", "HEAD"), cwd)).strip()

    async def _step(self, session: Session, step: str, argv: Sequence[str], cwd: Path) -> str:
        try:
            return await self._run(argv, cwd)
        except CommandError as error:
            stderr = error.stderr
        except OSError as error:  # the tool is not installed
            stderr = str(error)
        raise await self._failure(session, step, stderr)

    async def _failure(self, session: Session, step: str, stderr: str) -> GitActionError:
        """The step's failure, announced; for the caller to raise."""
        failure = GitActionError(step, stderr)
        await self._bus.publish(
            types.GIT_FAILED, {"step": step, "stderr": failure.stderr}, session.id
        )
        return failure


def _git(*args: str) -> list[str]:
    return ["git", *HARDENED, *args]
