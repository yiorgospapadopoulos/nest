"""Commit, push and open a pull request with the daemon's own git and gh setup (D004).

Each step is announced as an event; a failure publishes `git.failed` and stops. A retry
skips what is done: nothing is committed twice, pushing again is harmless, and a pull
request is opened once.

The tree and its git config may hold what the agent planted, so (D050): every git command
runs with `HARDENED` overrides (no hooks, no fsmonitor program), nothing starts while the
repository's own config sets something that runs a program or sends data elsewhere, and a
push goes only to the origin URL the user confirmed, sent to the URL that was checked, so
a later change is never followed (B159 P-7). Both checks run again right before the push,
since a process the agent left running could change the config meanwhile (SEC-07).

The commit is the reviewed work itself (B159 P-1): its tree is built in an index of its
own from the objects the review was made of, it gets the checked HEAD as its parent, and
the branch moves to it only while it still holds that HEAD; nothing reads the working
files again. The push sends that commit by SHA in an explicit refspec, without tags, to
the branch the review showed (B159 P-4), only a plain branch name: the agent can name a
branch `--mirror` and check it out (SEC-01, SEC-15). A worktree is pushed only from its
own branch (SEC-06), and a git repository inside the work is never committed (BUG-65).
A run that may not push itself never gets commits the review did not show pushed through
Approve (B159 P-2). gh opens the pull request from a folder outside the checkout when it
is told the repository, so it reads nothing the agent wrote (SEC-17).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.remotes import REMOTE, github_repo, scrub_url
from nestd.gitops.runner import CommandError, CommandRunner
from nestd.gitops.safety import GIT_CONFIG_LIST, HARDENED, repo_settings, unsafe_settings
from nestd.review.errors import (
    GitActionError,
    HeadChangedError,
    NestedRepositoryError,
    NothingToCommitError,
    RemoteChangedError,
    RemoteNotConfirmedError,
    ReviewChangedError,
    UnreviewedCommitsError,
    UnsafeBranchError,
    UnsafeRepoConfigError,
)
from nestd.review.snapshot import IndexEntry, index_updates, write_tree
from nestd.sessions.models import Session
from nestd.sessions.rules import pr_finished, require_cwd
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
    # The branch HEAD named in the review, None when detached; the commit goes there, and
    # a push only there (B159 P-4).
    branch: str | None
    # The reviewed work, each change as the object the review showed (B159 P-1).
    entries: tuple[IndexEntry, ...]
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
        # (`unsafe_repo_config`); a checkout no longer on the reviewed branch
        # (`review_changed`); for a push, origin's URL (`remote_not_confirmed`,
        # `remote_changed`), the branch (`unsafe_branch`) and, for a run that may not push
        # itself, commits the review did not show (`unreviewed_commits`); an untracked
        # nested repository (`nested_repository`); a branch that moved off the checked HEAD
        # (`head_changed`); then, before the push, the config and origin's URL again. A git
        # or gh failure is a 502 with its step.
        cwd = require_cwd(session)
        await self.require_safe_config(session)
        ref = await self._reviewed_ref(session, cwd, plan.branch)
        branch = None
        if plan.push:
            url = await self.require_remote(session, plan.remote_url)
            branch = await self._branch(session, ref)
            if _may_not_push(session):
                await self._require_seen(session, cwd, plan.head, url)
        await self._refuse_nested(session, cwd, plan.paths)
        session, sha = await self._commit(session, cwd, plan, ref)
        if branch is None:
            return session
        await self.require_safe_config(session)
        url = await self.require_remote(session, plan.remote_url)
        push = [
            *("push", "--no-verify", "--recurse-submodules=no", "--no-follow-tags"),
            *("--", url, f"{sha}:refs/heads/{branch}"),
        ]
        await self._step(session, "push", _git(*push), cwd)
        await self._track(session, cwd, branch, sha)
        await self._bus.publish(types.GIT_PUSHED, {"remote": REMOTE, "branch": branch}, session.id)
        if plan.pull_request is None or (session.pr_url is not None and not pr_finished(session)):
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
        session = await self._store.update(
            session.id, pr_url=url, pr_summary=pr.summary, pr=None, review=None
        )
        await self._bus.publish(types.PR_OPENED, {"url": url}, session.id)
        return session

    async def push_rebased(
        self, session: Session, sha: str, lease: str, remote_url: str | None
    ) -> str:
        """Push a stacked chat's branch after Nest rebased it (B149): a force push of `sha`
        to the session's branch, only while GitHub still has `lease` there, with the same
        checks as any push. Returns the branch.
        """
        cwd = require_cwd(session)
        await self.require_safe_config(session)
        url = await self.require_remote(session, remote_url)
        branch = await self._branch(session, await self._head_ref(cwd))
        push = [
            *("push", "--no-verify", "--recurse-submodules=no", "--no-follow-tags"),
            f"--force-with-lease=refs/heads/{branch}:{lease}",
            *("--", url, f"{sha}:refs/heads/{branch}"),
        ]
        await self._step(session, "push", _git(*push), cwd)
        await self._step(session, "push", _git("update-ref", _tracking(branch), sha), cwd)
        await self._bus.publish(
            types.GIT_PUSHED, {"remote": REMOTE, "branch": branch, "rebased": True}, session.id
        )
        return branch

    async def require_safe_config(self, session: Session) -> None:
        """Refuse while the repository's own config would run a program (D050)."""
        cwd = require_cwd(session)
        listing = await self._step(session, "commit", _git(*GIT_CONFIG_LIST[1:]), cwd)
        unsafe = unsafe_settings(repo_settings(listing))
        if unsafe:
            await self._refuse(session, "commit", UnsafeRepoConfigError(unsafe))

    async def require_remote(self, session: Session, confirmed_url: str | None) -> str:
        """Refuse unless origin pushes to the confirmed URL, and only there (D050). Returns
        that URL as origin names it, credentials included, for the push to name itself, so
        a change after this check is never followed (B159 P-7).
        """
        listing = _git("remote", "get-url", "--push", "--all", REMOTE)
        try:
            output = await self._run(listing, require_cwd(session))
        except CommandError:
            output = ""
        urls = [line for line in output.splitlines() if line]
        current = [scrub_url(url) for url in urls]
        if confirmed_url is None:
            await self._refuse(session, "push", RemoteNotConfirmedError(current))
        if current != [confirmed_url]:
            await self._refuse(session, "push", RemoteChangedError(current, confirmed_url))
        return urls[0]

    async def _refuse(self, session: Session, step: str, error: Exception) -> NoReturn:
        await self._bus.publish(types.GIT_FAILED, {"step": step, "stderr": str(error)}, session.id)
        raise error

    async def _reviewed_ref(self, session: Session, cwd: Path, branch: str | None) -> str | None:
        """The ref HEAD names, which must be the branch the review showed (None: detached).
        Nest's commit goes to this ref, and a push to this branch, whatever HEAD names
        later (B159 P-4).
        """
        ref = await self._head_ref(cwd)
        if (None if ref is None else ref.removeprefix("refs/heads/")) != branch:
            await self._refuse(session, "commit", ReviewChangedError())
        return ref

    async def _head_ref(self, cwd: Path) -> str | None:
        try:
            return (await self._run(_git("symbolic-ref", "-q", "HEAD"), cwd)).strip() or None
        except CommandError:
            return None  # detached

    async def _branch(self, session: Session, ref: str | None) -> str:
        """The branch `ref` names, which must be a plain branch name, and for a worktree its
        session's branch.
        """
        head = ref or "HEAD"
        branch = head.removeprefix("refs/heads/")
        if session.branch is not None and branch != session.branch:
            await self._refuse(session, "push", UnsafeBranchError(branch, session.branch))
        if branch == head or branch.startswith("-"):
            await self._refuse(session, "push", UnsafeBranchError(branch))
        try:
            await self._run(_git("check-ref-format", "--branch", branch), require_cwd(session))
        except CommandError:
            await self._refuse(session, "push", UnsafeBranchError(branch))
        return branch

    async def _require_seen(self, session: Session, cwd: Path, head: str | None, url: str) -> None:
        """Refuse when the push would send commits besides Nest's own, which the review
        never showed. What origin has is asked of origin, as a local ref could say anything.
        """
        if head is None:
            return
        listing = await self._step(session, "push", _git("ls-remote", "--heads", "--", url), cwd)
        known = [line.split("\t", 1)[0] for line in listing.splitlines() if line]
        rev_list = _git("rev-list", "--ignore-missing", head, "--not", *known, "--")
        new = (await self._step(session, "push", rev_list, cwd)).split()
        if not new:
            return
        events = await self._bus.session_events(session.id)
        nests = {str(e.payload.get("sha")) for e in events if e.type == types.GIT_COMMITTED}
        unseen = [sha for sha in new if sha not in nests]
        if unseen:
            await self._refuse(session, "push", UnreviewedCommitsError(unseen))

    async def _commit(
        self, session: Session, cwd: Path, plan: PublishPlan, ref: str | None
    ) -> tuple[Session, str]:
        """Commit the reviewed work; the session and the commit a push sends."""
        chosen = None if plan.paths is None else set(plan.paths)
        entries = [e for e in plan.entries if chosen is None or e.path in chosen]
        if not entries:
            if plan.head is None or plan.head != session.commit_sha:
                msg = "there are no changes to commit"
                raise NothingToCommitError(msg)
            # Committed by an earlier attempt, whose push failed.
            return session, plan.head
        try:
            tree = await write_tree(cwd, plan.head, entries)
        except CommandError as error:
            raise await self._failure(session, "commit", error.stderr) from None
        message = _cleanup(plan.message)
        parent = () if plan.head is None else ("-p", plan.head)
        commit = _git("commit-tree", tree, *parent, "-m", message)
        sha = (await self._step(session, "commit", commit, cwd)).strip()
        await self._move(session, cwd, ref, sha, plan.head, message)
        session = await self._store.update(session.id, commit_sha=sha)
        await self._bus.publish(types.GIT_COMMITTED, {"sha": sha}, session.id)
        await self._stage(session, cwd, entries)
        return session, sha

    async def _move(
        self, session: Session, cwd: Path, ref: str | None, sha: str, head: str | None, message: str
    ) -> None:
        """Point the branch (or a detached HEAD) at Nest's commit, only while it still holds
        the checked HEAD: something committed since is never replaced, nor published
        (SEC-15).
        """
        subject = message.split("\n", 1)[0]
        reflog = f"commit: {subject}" if head is not None else f"commit (initial): {subject}"
        target = ["--no-deref", "HEAD"] if ref is None else [ref]
        update = _git("update-ref", "-m", reflog, *target, sha, head or "")
        try:
            await self._run(update, cwd)
        except CommandError:
            await self._refuse(session, "commit", HeadChangedError())

    async def _stage(self, session: Session, cwd: Path, entries: Sequence[IndexEntry]) -> None:
        """Record the commit in the checkout's index too, as `git commit` would, leaving any
        other staged change alone.
        """
        for update in index_updates(entries):
            await self._step(session, "commit", _git("update-index", *update), cwd)

    async def _track(self, session: Session, cwd: Path, branch: str, sha: str) -> None:
        """Record origin's branch as the upstream, as `push -u origin` does, since the push
        names a URL.
        """
        await self._step(session, "push", _git("update-ref", _tracking(branch), sha), cwd)
        for key, value in (("remote", REMOTE), ("merge", f"refs/heads/{branch}")):
            config = _git("config", f"branch.{branch}.{key}", value)
            await self._step(session, "push", config, cwd)

    async def _refuse_nested(self, session: Session, cwd: Path, paths: list[str] | None) -> None:
        """Refuse an untracked git repository inside the work, which git lists as its folder,
        `lib/`.
        """
        listing = ("ls-files", "-z", "--others", "--exclude-standard")
        chosen = () if paths is None else ("--", *paths)
        untracked = await self._step(session, "commit", _git(*listing, *chosen), cwd)
        nested = sorted({path for path in untracked.split("\0") if path.endswith("/")})
        if nested:
            await self._refuse(session, "commit", NestedRepositoryError(nested))

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


def _may_not_push(session: Session) -> bool:
    """A run Nest stops from pushing while the user has not let agents push: as for the git
    guard in `sessions.turns`, pixie runs, Autopilot and chats a trigger or an outside
    client started (D160).
    """
    return (
        session.pixie_id is not None
        or session.started_by_pixie is not None
        or session.autopilot is not None
        or session.started_by_trigger is not None
        or session.started_by_client is not None
    )


def _cleanup(message: str) -> str:
    """The message as `git commit -m` keeps it: no trailing spaces, no blank lines at
    either end, and no runs of blank lines.
    """
    lines: list[str] = []
    for line in message.splitlines():
        line = line.rstrip()
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip("\n")


def _tracking(branch: str) -> str:
    return f"refs/remotes/{REMOTE}/{branch}"


def _git(*args: str) -> list[str]:
    return ["git", *HARDENED, *args]
