"""A project's GitHub triggers, kept in its config as `[[triggers]]` (B148)."""

from uuid import uuid4

from nestd.errors import InvalidInputError, NotFoundError
from nestd.issues.service import github_repo_of
from nestd.repos.service import RepoService
from nestd.triggers.models import ChatTrigger, NewChatTrigger, TriggerActivity, UpdateChatTrigger
from nestd.triggers.store import TriggerStore


class TriggerNotFoundError(NotFoundError):
    pass


class ChatTriggerService:
    def __init__(self, repos: RepoService, store: TriggerStore) -> None:
        self._repos = repos
        self._store = store

    def of_repo(self, repo: str) -> list[ChatTrigger]:
        return self._repos.registered(repo).triggers

    async def activity(self, repo: str) -> list[TriggerActivity]:
        """What each of the project's triggers did last; one that did nothing is left out."""
        last = await self._store.last(t.id for t in self.of_repo(repo))
        return list(last.values())

    async def create(self, repo: str, request: NewChatTrigger) -> ChatTrigger:
        """422 unless the project is a git repository with a GitHub remote."""
        config = self._repos.registered(repo)
        if config.git and github_repo_of(config) is None:
            msg = f"{repo} has no GitHub remote, so Nest cannot watch it"
            raise InvalidInputError(msg)
        trigger = ChatTrigger(**request.model_dump(), id=uuid4().hex)
        await self._save(repo, [*config.triggers, trigger])
        return trigger

    async def update(self, repo: str, trigger_id: str, request: UpdateChatTrigger) -> ChatTrigger:
        """Fields left out are unchanged."""
        triggers = self.of_repo(repo)
        before = _find(triggers, trigger_id)
        after = ChatTrigger.model_validate(
            {**before.model_dump(), **request.model_dump(exclude_none=True)}
        )
        await self._save(repo, [after if t.id == trigger_id else t for t in triggers])
        return after

    async def delete(self, repo: str, trigger_id: str) -> None:
        triggers = self.of_repo(repo)
        _find(triggers, trigger_id)
        await self._save(repo, [t for t in triggers if t.id != trigger_id])

    async def _save(self, repo: str, triggers: list[ChatTrigger]) -> None:
        """Saved and announced with the project; a plain folder is refused there."""
        await self._repos.edit(repo, {"triggers": [t.model_dump() for t in triggers]})


def _find(triggers: list[ChatTrigger], trigger_id: str) -> ChatTrigger:
    for trigger in triggers:
        if trigger.id == trigger_id:
            return trigger
    msg = f"unknown trigger {trigger_id!r}"
    raise TriggerNotFoundError(msg)
