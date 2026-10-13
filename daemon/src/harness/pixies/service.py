"""Create, change and delete pixies, and route messages to each pixie's chat (D057)."""

import asyncio
from collections.abc import Callable
from contextlib import suppress

from harness.clock import Clock
from harness.config.models import AgentDefaults
from harness.events import types
from harness.events.bus import EventBus
from harness.pixies.files import PixieFiles
from harness.pixies.models import (
    CreatePixie,
    FileText,
    Pixie,
    PixieSettings,
    SearchHit,
    UpdatePixie,
    WriteFile,
)
from harness.pixies.slugs import RESERVED_SLUGS, check_slug, slugify
from harness.pixies.store import PixieStore
from harness.sessions.errors import SessionNotFoundError
from harness.sessions.manager import SessionManager
from harness.sessions.models import Session, SessionState, UpdateSession

DEFAULT_SOUL = (
    "You are a helpful pixie. Describe here who you are, what you do, how you like to work "
    "and what you should never do."
)
# Changing these on a pixie changes its open chat as well.
_CONTROLS = ("model", "effort", "permission_mode")
# Changing these changes what the chat's run is opened with, so its next turn opens a new one.
_RUN_SHAPING = (
    "name",
    "slug",
    "project_access",
    "projects",
    "skills",
    "can_call",
    "allowed_tools",
    "disallowed_tools",
)
# Files the run's system prompt is built from.
_PROMPT_FILES = ("soul", "memory")


class PixieService:
    def __init__(
        self,
        store: PixieStore,
        files: PixieFiles,
        sessions: SessionManager,
        bus: EventBus,
        clock: Clock,
        defaults: Callable[[], AgentDefaults],
    ) -> None:
        self._store = store
        self._files = files
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
        check_slug(slug)
        settings = PixieSettings.model_validate(request.model_dump(exclude={"slug", "soul"}))
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
        changes = request.model_dump(exclude_none=True, exclude={"all_projects"})
        if request.all_projects:
            changes["projects"] = None
        if "slug" in changes:
            check_slug(changes["slug"])
        pixie = await self._store.update(pixie_id, **changes)
        chat = pixie.chat_session_id
        controls = {name: changes[name] for name in _CONTROLS if name in changes}
        if "name" in changes:
            controls["title"] = changes["name"]
        if controls and chat is not None:
            # A chat that is gone has nothing to change; the pixie's row already did.
            with suppress(SessionNotFoundError):
                await self._sessions.update(chat, UpdateSession(**controls))
        if chat is not None and any(name in changes for name in _RUN_SHAPING):
            self._sessions.refresh_run(chat)
        await self._announce(pixie)
        return pixie

    async def delete(self, pixie_id: str) -> None:
        async with self._lock(pixie_id):
            pixie = await self._store.get(pixie_id)
            chats = await self._store.chat_sessions(pixie_id)
            await self._store.set_chat(pixie_id, None)
            for session_id in chats:
                await self._sessions.purge(session_id)
            await self._store.delete(pixie_id)
            self._files.remove(pixie.id)
            await self._bus.publish(types.PIXIE_DELETED, {"pixie_id": pixie_id})
        # Only now: a send that waited on the lock still finds it and sees no pixie.
        self._locks.pop(pixie_id, None)

    async def send(self, pixie_id: str, text: str, attachment_ids: list[str]) -> Session:
        async with self._lock(pixie_id):
            pixie = await self._store.get(pixie_id)
            chat = await self._open_chat(pixie)
            if chat is not None:
                return await self._sessions.send(chat.id, text, attachment_ids)
            defaults = self._defaults()
            session = await self._sessions.create_pixie_chat(
                pixie_id=pixie.id,
                cwd=self._files.workdir(pixie.id),
                prompt=text,
                title=pixie.name,
                model=pixie.model or defaults.model,
                effort=pixie.effort,
                permission_mode=pixie.permission_mode,
                attachment_ids=attachment_ids,
            )
            await self._announce(await self._store.set_chat(pixie.id, session.id))
            return session

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

    async def search(self, pixie_id: str, query: str) -> list[SearchHit]:
        await self._store.get(pixie_id)
        return self._files.search(pixie_id, query)

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
        taken = await self._store.slugs() | RESERVED_SLUGS
        slug, n = base, 2
        while slug in taken:
            suffix = f"-{n}"
            slug, n = base[: 32 - len(suffix)] + suffix, n + 1
        return slug

    async def _announce(self, pixie: Pixie) -> None:
        await self._bus.publish(types.PIXIE_UPDATED, {"pixie": pixie.model_dump(mode="json")})
