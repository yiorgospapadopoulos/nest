"""Follow a pull request the agent opened itself when the user asked (D085, B101).

Nest follows the pull requests its Approve opens. When a worktree chat's turn ends without
one, the daemon asks gh once for the user's own open pull requests from its branch. One
whose head is the chat's own push repository (not a fork with a branch of the same name)
and that no other chat follows becomes the chat's, as if Nest had opened it. Nothing is
written to GitHub, and the read runs beside the turn's end, never holding it up.
"""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from nestd.config.models import RepoConfig
from nestd.errors import NotFoundError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.runner import CommandError, CommandRunner
from nestd.issues.service import github_repo_of
from nestd.sessions.models import Session, SessionState
from nestd.sessions.store import SessionStore

logger = logging.getLogger(__name__)


class _Owner(BaseModel):
    login: str


class _Repository(BaseModel):
    name: str


class _Listed(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    number: int
    url: str
    head_owner: _Owner | None = Field(default=None, alias="headRepositoryOwner")
    head_repository: _Repository | None = Field(default=None, alias="headRepository")

    def head(self) -> str | None:
        """The head repository's `owner/name`; None when GitHub no longer has it."""
        if self.head_owner is None or self.head_repository is None:
            return None
        return f"{self.head_owner.login}/{self.head_repository.name}"


_LIST = TypeAdapter(list[_Listed])
# Pull requests read; forks may have a branch of the same name.
LIST_LIMIT = 5


class PrAdopter:
    """A state follower of the session reactions."""

    def __init__(
        self,
        *,
        store: SessionStore,
        bus: EventBus,
        repo: Callable[[str], RepoConfig],
        run: CommandRunner,
        cwd: Path,
        check_soon: Callable[[str], None],
    ) -> None:
        """`repo` finds a project by name; `cwd` is a folder outside any checkout;
        `check_soon` has the pull request monitor read an adopted one at once.
        """
        self._store = store
        self._bus = bus
        self._repo = repo
        self._run = run
        self._cwd = cwd
        self._check_soon = check_soon
        # The read under way for each session; one at a time.
        self._reads: dict[str, asyncio.Task[None]] = {}

    async def state_changed(self, session: Session) -> None:
        if session.state is not SessionState.IDLE or session.id in self._reads:
            return
        if session.pr_url is not None or session.pixie_id is not None:
            return
        if session.worktree_path is None or session.branch is None:
            return
        try:
            repo = self._repo(session.repo)
        except NotFoundError:
            return
        where = github_repo_of(repo)
        if where is None or session.branch == repo.default_branch:
            return
        task = asyncio.create_task(self._look(session.id, where, session.branch))
        self._reads[session.id] = task
        task.add_done_callback(lambda _: self._reads.pop(session.id, None))

    async def purged(self, session_id: str) -> None:
        """Nothing is kept for a deleted chat; a read under way finds it gone."""

    async def settled(self) -> None:
        """Wait for the reads under way, as tests and shutdown do."""
        await asyncio.gather(*self._reads.values(), return_exceptions=True)

    async def _look(self, session_id: str, where: str, branch: str) -> None:
        argv = [
            *("gh", "pr", "list", "--repo", where, "--head", branch, "--author", "@me"),
            *("--state", "open", "--json", "url,number,headRepositoryOwner,headRepository"),
            *("--limit", str(LIST_LIMIT)),
        ]
        try:
            found = _LIST.validate_json(await self._run(argv, self._cwd))
        except (CommandError, OSError, ValidationError) as error:
            # gh output can quote anything, so only the kind of failure is logged.
            logger.warning(
                "could not look for a pull request of %s (%s)", where, type(error).__name__
            )
            return
        own = [pr for pr in found if (pr.head() or "").lower() == where.lower()]
        if not own:
            return
        url = own[0].url
        others = await self._store.with_prs()
        if any(other.pr_url == url for other in others):
            return
        try:
            session = await self._store.get(session_id)
        except NotFoundError:
            return
        if session.pr_url is not None:
            return
        await self._store.update(session_id, pr_url=url)
        await self._bus.publish(types.PR_OPENED, {"url": url}, session_id)
        self._check_soon(session_id)
