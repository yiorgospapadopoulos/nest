"""Create, change and delete pixies, and route messages to each pixie's chat (D072)."""

import asyncio
from collections.abc import Callable
from contextlib import suppress

from nestd.clock import Clock
from nestd.config.models import AgentDefaults
from nestd.engine.defaults import default_effort
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.pixies.activity import ActivityStore
from nestd.pixies.errors import DuplicateSlugError
from nestd.pixies.files import PixieFiles
from nestd.pixies.models import (
    DEFAULT_PROVIDER,
    NAME_MAX,
    CreatePixie,
    FileText,
    Pixie,
    PixieActivity,
    PixieSettings,
    SearchHit,
    UpdatePixie,
    WriteFile,
    run_model,
)
from nestd.pixies.slugs import check_slug, free_slug, slugify
from nestd.pixies.store import PixieStore
from nestd.pixies.teams import TeamService
from nestd.sessions.engines import Engine
from nestd.sessions.errors import SessionNotFoundError, UnsupportedFeatureError
from nestd.sessions.manager import SessionManager
from nestd.sessions.models import (
    USER,
    Sender,
    SendResult,
    Session,
    SessionState,
    UpdateSession,
)

DEFAULT_SOUL = (
    "You are a helpful pixie. Describe here who you are, what you do, how you like to work "
    "and what you should never do."
)
# Changing these on a pixie changes its open chat as well.
_CONTROLS = ("model", "effort", "permission_mode")
# An explicit null sets these back to the default; for the other fields null is no change.
_CLEARABLE = ("model", "effort")
# Changing these changes what the chat's run is opened with, so its next turn opens a new one.
_RUN_SHAPING = (
    "name",
    "slug",
    # The run's prompt names it; the tools check it on every call anyway (B41).
    "autonomy",
    "project_access",
    "skills",
    "can_call",
)
# Files the run's system prompt is built from.
_PROMPT_FILES = ("soul", "memory")


class PixieService:
    def __init__(
        self,
        store: PixieStore,
        files: PixieFiles,
        teams: TeamService,
        sessions: SessionManager,
        bus: EventBus,
        clock: Clock,
        defaults: Callable[[], AgentDefaults],
        activity: ActivityStore,
    ) -> None:
        self._activity = activity
        self._store = store
        self._files = files
        self._teams = teams
        self._sessions = sessions
        self._bus = bus
        self._clock = clock
        self._defaults = defaults
        # One message at a time per pixie, so two first messages make one chat.
        self._locks: dict[str, asyncio.Lock] = {}

    async def list_pixies(self) -> list[Pixie]:
        return await self._store.list_pixies()

    async def get(self, pixie_id: str) -> Pixie:
        return await self._store.get(pixie_id)

    async def create(self, request: CreatePixie) -> Pixie:
        slug = request.slug or await self._free_slug(slugify(request.name))
        await self._check_slug(slug)
        engine = self._engine(request.provider)
        _require_skills(engine, request.skills)
        model = request.model or await self._new_model(engine)
        await self._sessions.fitting_mode(
            model,
            request.permission_mode,
            request.permission_mode,
            model_changed=False,
            engine=engine,
        )
        effort = request.effort or default_effort(await engine.find(model))
        settings = PixieSettings.model_validate(
            request.model_dump(exclude={"slug", "soul"}) | {"model": model, "effort": effort}
        )
        pixie = await self._store.create(settings, slug)
        try:
            self._files.create(pixie.id, request.soul.strip() or DEFAULT_SOUL)
        except OSError:
            # No pixie without its folder.
            await self._store.delete(pixie.id)
            self._files.remove(pixie.id)
            raise
        await self._announce(pixie)
        return pixie

    async def update(self, pixie_id: str, request: UpdatePixie) -> Pixie:
        changes = request.model_dump(exclude_none=True, exclude={"team_id"})
        cleared = {
            name
            for name in _CLEARABLE
            if name in request.model_fields_set and getattr(request, name) is None
        }
        changes |= dict.fromkeys(cleared)
        if "slug" in changes:
            await self._check_slug(changes["slug"])
        before = await self._store.get(pixie_id)
        if "team_id" in request.model_fields_set:
            if request.team_id is not None:
                await self._teams.get(request.team_id)  # unknown: nothing changes
            changes["team_id"] = request.team_id
        moved = changes.get("provider", before.provider) != before.provider
        if moved:
            # The old engine's model and thinking mean nothing on the new one.
            for name in _CLEARABLE:
                changes.setdefault(name, None)
        engine = self._engine(changes.get("provider", before.provider))
        _require_skills(engine, request.skills)
        default_model = await self._new_model(engine)
        # Back to the default: the concrete model and thinking Nest picks (B94).
        if "model" in changes and changes["model"] is None:
            changes["model"] = default_model
        if "effort" in changes and changes["effort"] is None:
            model = changes.get("model", before.model) or default_model
            changes["effort"] = default_effort(await engine.find(model))
        mode = await self._sessions.fitting_mode(
            changes.get("model", before.model) or default_model,
            changes.get("permission_mode"),
            before.permission_mode,
            model_changed="model" in changes,
            engine=engine,
        )
        if mode is not None:
            changes["permission_mode"] = mode
        pixie = await self._store.update(pixie_id, **changes)
        if moved and pixie.chat_session_id is not None:
            # Its chat stays on the engine it began on: the next message starts a new one.
            await self._sessions.update(pixie.chat_session_id, UpdateSession(archived=True))
            pixie = await self._store.set_chat(pixie_id, None)
        chat = pixie.chat_session_id
        controls = {name: changes[name] for name in _CONTROLS if name in changes}
        if "model" in controls:
            # The chat runs the default model by name, as a new chat would (`send`).
            controls["model"] = pixie.model or default_model
        if "name" in changes:
            controls["title"] = changes["name"]
        if controls and chat is not None:
            # A chat that is gone has nothing to change; the pixie's row already did.
            with suppress(SessionNotFoundError):
                await self._sessions.set_pixie_controls(chat, controls)
        if chat is not None and (cleared or any(name in changes for name in _RUN_SHAPING)):
            self._sessions.refresh_run(chat)
        if pixie.team_id != before.team_id:
            await self._teams.member_moved(pixie.id, before.team_id, pixie.team_id)
        await self._announce(pixie)
        return pixie

    async def duplicate(self, pixie_id: str) -> Pixie:
        """A copy right after the original, in its team (never as leader): every setting,
        the soul, memory, notes and archive, but not the chat or the workdir's files.
        Each pixie that moved down is announced (B40).
        """
        original = await self._store.get(pixie_id)
        names = {pixie.name for pixie in await self._store.list_pixies()}
        settings = PixieSettings.model_validate(
            original.model_dump(include=set(PixieSettings.model_fields))
        ).model_copy(update={"name": _copy_name(original.name, names)})
        copy, moved = await self._store.create_after(
            settings, await self._free_slug(original.slug), original.position, original.team_id
        )
        try:
            self._files.copy(original.id, copy.id)
        except OSError:
            await self._store.delete(copy.id)
            self._files.remove(copy.id)
            raise
        for moved_id in moved:
            await self._announce(await self._store.get(moved_id))
        await self._announce(copy)
        return copy

    async def reorder(self, ids: list[str]) -> list[Pixie]:
        """Puts the pixies in this order; each one that moved is announced."""
        moved = set(await self._store.reorder(ids))
        pixies = await self._store.list_pixies()
        for pixie in pixies:
            if pixie.id in moved:
                await self._announce(pixie)
        return pixies

    async def delete(self, pixie_id: str) -> None:
        async with self._lock(pixie_id):
            pixie = await self._store.get(pixie_id)
            chats = await self._store.chat_sessions(pixie_id)
            await self._store.set_chat(pixie_id, None)
            for session_id in chats:
                await self._sessions.purge(session_id)
            if pixie.team_id is not None:
                # Its team gets a new leader first, if it led it.
                await self._store.update(pixie_id, team_id=None)
                await self._teams.member_moved(pixie_id, pixie.team_id, None)
            await self._store.delete(pixie_id)
            self._files.remove(pixie.id)
            await self._bus.publish(types.PIXIE_DELETED, {"pixie_id": pixie_id})
        # Only now: a send that waited on the lock still finds it and sees no pixie.
        self._locks.pop(pixie_id, None)

    async def send(
        self, pixie_id: str, text: str, attachment_ids: list[str], sender: Sender = USER
    ) -> SendResult:
        """Starts the pixie's chat, or sends to the open one; `queued_message` is set when the
        message waits for the running turn. `sender` marks the daemon's own reports (B41).
        """
        async with self._lock(pixie_id):
            pixie = await self.settle(await self._store.get(pixie_id))
            chat = await self._open_chat(pixie)
            if chat is not None:
                return await self._sessions.send(chat.id, text, attachment_ids, sender=sender)
            session = await self._sessions.create_pixie_chat(
                pixie_id=pixie.id,
                cwd=self._files.workdir(pixie.id),
                prompt=text,
                title=pixie.name,
                model=run_model(pixie, self._defaults().model),
                effort=pixie.effort,
                permission_mode=pixie.permission_mode,
                attachment_ids=attachment_ids,
                sender=sender,
                provider=pixie.provider,
            )
            await self._announce(await self._store.set_chat(pixie.id, session.id))
            return SendResult(**session.model_dump())

    async def open_chat_id(self, pixie_id: str) -> str | None:
        """The pixie's chat a message would go to, or None when one would start a new one."""
        chat = await self._open_chat(await self._store.get(pixie_id))
        return None if chat is None else chat.id

    async def reset(self, pixie_id: str) -> Pixie:
        async with self._lock(pixie_id):
            pixie = await self._store.get(pixie_id)
            if pixie.chat_session_id is not None:
                await self._sessions.update(pixie.chat_session_id, UpdateSession(archived=True))
            pixie = await self._store.set_chat(pixie_id, None)
            await self._announce(pixie)
            return pixie

    async def read_file(self, pixie_id: str, name: str) -> FileText:
        await self._store.get(pixie_id)
        return self._files.read(pixie_id, name)

    async def write_file(self, pixie_id: str, name: str, body: WriteFile) -> FileText:
        pixie = await self._store.get(pixie_id)
        saved = self._files.write(pixie_id, name, body.text, body.hash)
        if name in _PROMPT_FILES and pixie.chat_session_id is not None:
            self._sessions.refresh_run(pixie.chat_session_id)
        return saved

    async def notes(self, pixie_id: str) -> list[str]:
        await self._store.get(pixie_id)
        return self._files.notes(pixie_id)

    async def activity(self, pixie_id: str) -> list[PixieActivity]:
        """What the pixie did through its Nest tools, newest first (B41)."""
        await self._store.get(pixie_id)
        return await self._activity.list(pixie_id)

    async def search(self, pixie_id: str, query: str) -> list[SearchHit]:
        await self._store.get(pixie_id)
        return self._files.search(pixie_id, query)

    def _engine(self, provider: str) -> Engine:
        """The pixie's engine: Claude's name is the default engine; any other must be one
        Nest runs (422).
        """
        engines = self._sessions.engines
        return engines.default if provider == DEFAULT_PROVIDER else engines.named(provider)

    async def settle(self, pixie: Pixie) -> Pixie:
        """A pixie stored without a model or thinking level of its own (before B94, or
        made before its engine's list was known) gets the concrete ones Nest picks, once
        its engine's list knows the model; announced when they change.
        """
        if pixie.model is not None and pixie.effort is not None:
            return pixie
        engine = self._engine(pixie.provider)
        model = pixie.model or await self._new_model(engine)
        option = None if model is None else await engine.find(model)
        if option is None:
            return pixie
        changes: dict[str, object] = {}
        if pixie.model is None:
            changes["model"] = model
        if pixie.effort is None and (effort := default_effort(option)) is not None:
            changes["effort"] = effort
        if not changes:
            return pixie
        settled = await self._store.update(pixie.id, **changes)
        await self._announce(settled)
        return settled

    async def settle_all(self) -> None:
        for pixie in await self._store.list_pixies():
            await self.settle(pixie)

    async def _new_model(self, engine: Engine) -> str | None:
        """The model a pixie gets when none is chosen: the agent defaults' on their engine,
        else the engine's own default model (B94); None while it is not known.
        """
        agents = self._defaults()
        engines = self._sessions.engines
        own = engines.default if agents.provider is None else engines.by_name(agents.provider)
        if engine is own and agents.model is not None:
            return agents.model
        return await engine.default_model()

    def _lock(self, pixie_id: str) -> asyncio.Lock:
        return self._locks.setdefault(pixie_id, asyncio.Lock())

    async def _open_chat(self, pixie: Pixie) -> Session | None:
        if pixie.chat_session_id is None:
            return None
        try:
            chat = await self._sessions.get(pixie.chat_session_id)
        except SessionNotFoundError:
            return None
        if chat.state is SessionState.CLOSED or chat.archived_at is not None:
            return None
        return chat

    async def _free_slug(self, base: str) -> str:
        return free_slug(base, await self._store.slugs() | await self._teams.handles())

    async def _check_slug(self, slug: str) -> None:
        """A valid slug that no team uses; a pixie using it is the store's conflict."""
        check_slug(slug)
        if slug in await self._teams.handles():
            msg = f"a team called @{slug} already exists"
            raise DuplicateSlugError(msg)

    async def _announce(self, pixie: Pixie) -> None:
        await self._bus.publish(types.PIXIE_UPDATED, {"pixie": pixie.model_dump(mode="json")})


def _require_skills(engine: Engine, skills: list[str] | None) -> None:
    """409 when a skill list is set on a pixie whose engine takes none (Codex, B91). A list
    stored before it moved there stays, unused; clearing it is allowed.
    """
    if skills and not engine.supports("pixie_skills"):
        raise UnsupportedFeatureError(engine.name, "pixie_skills")


def _copy_name(name: str, taken: set[str]) -> str:
    """`<name> 2`, or the next free number, trimmed to fit a name's length."""
    n = 2
    while True:
        suffix = f" {n}"
        candidate = name[: NAME_MAX - len(suffix)].rstrip() + suffix
        if candidate not in taken:
            return candidate
        n += 1
