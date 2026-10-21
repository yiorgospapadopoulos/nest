"""A project's open GitHub issues for new chats, and one issue when a chat starts from it
(B101). Issues are read with the user's `gh` login and never written.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from nestd.clock import Clock
from nestd.config.models import IssueShow, RepoConfig
from nestd.gitops.remotes import github_repo
from nestd.gitops.runner import CommandError, CommandRunner
from nestd.issues.errors import IssueClosedError, IssueReadError, NoGitHubRemoteError
from nestd.issues.github import list_issues, parse_issue, parse_issue_list, view_issue
from nestd.issues.models import Issue, IssueList

logger = logging.getLogger(__name__)

CACHE_TTL = timedelta(seconds=60)

# The id of the chat started from each issue of a project, by issue number.
type IssueChats = Callable[[str], Awaitable[dict[int, str]]]


class IssueService:
    def __init__(
        self,
        *,
        repo: Callable[[str], RepoConfig],
        run: CommandRunner,
        clock: Clock,
        cwd: Path,
        chats: IssueChats,
    ) -> None:
        """`repo` finds a project's config by name; `cwd` is a folder outside any checkout;
        `chats` finds the chat started from each issue of a project.
        """
        self._chats = chats
        self._repo = repo
        self._run = run
        self._clock = clock
        self._cwd = cwd
        # By repository and choice: when it was read, and the answer.
        self._cache: dict[tuple[str, IssueShow], tuple[datetime, IssueList]] = {}

    async def list_issues(
        self, name: str, refresh: bool = False, show: IssueShow | None = None
    ) -> IssueList:
        """The project's open issues, newest updated first; read again after a minute.
        `show` chooses all of them or the user's own, over the project's `[issues] show`.
        """
        repo = self._repo(name)
        show = show or repo.issues.show
        where = github_repo_of(repo)
        if where is None:
            return IssueList(available=False, show=show, issues=[])
        now = self._clock.now()
        cached = self._cache.get((where, show))
        if not refresh and cached is not None and now - cached[0] < CACHE_TTL:
            return await self._with_chats(name, cached[1])
        what = f"the issues of {where}"
        try:
            output = await list_issues(self._run, self._cwd, where, mine=show == "mine")
            issues = parse_issue_list(output, where)
        except (CommandError, OSError, ValidationError) as error:
            raise _failed(what, error) from None
        listed = IssueList(available=True, show=show, issues=issues)
        self._cache[(where, show)] = (now, listed)
        return await self._with_chats(name, listed)

    async def _with_chats(self, name: str, listed: IssueList) -> IssueList:
        """Each issue with its chat as the sessions say now; the cache keeps none."""
        chats = await self._chats(name)
        issues = [
            issue.model_copy(update={"chat": chats.get(issue.number)}) for issue in listed.issues
        ]
        return listed.model_copy(update={"issues": issues})

    async def fetch(self, repo: RepoConfig, number: int) -> Issue:
        """One open issue of the project, with its comments by people."""
        where = github_repo_of(repo)
        if where is None:
            raise NoGitHubRemoteError(repo.name)
        try:
            issue = parse_issue(await view_issue(self._run, self._cwd, where, number))
        except (CommandError, OSError, ValidationError) as error:
            raise _failed(f"issue #{number} of {where}", error) from None
        if issue.state != "open":
            raise IssueClosedError(number)
        return issue


def github_repo_of(repo: RepoConfig) -> str | None:
    """`owner/name` from the remote URL the user confirmed, which no agent can change."""
    return None if repo.remote_url is None else github_repo(repo.remote_url)


def _failed(what: str, error: Exception) -> IssueReadError:
    # gh output can quote anything, so only the kind of failure is logged.
    logger.warning("could not read %s (%s)", what, type(error).__name__)
    return IssueReadError(what, error)
