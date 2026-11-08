"""Computer use for chats (B150, D178): who may use it, the user's approvals, one chat per
target, and the screenshots clients show while it works."""

import asyncio
import itertools
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, JsonValue

from nestd.computer.backends.base import Backend
from nestd.computer.locks import TargetLocks
from nestd.computer.models import (
    KINDS,
    Action,
    ActResult,
    Availability,
    Element,
    NeedsFrontError,
    TargetError,
    TargetInfo,
    View,
    kind_of,
)
from nestd.computer.safety import is_secret, risk
from nestd.config.models import ComputerUseSettings
from nestd.errors import ConflictError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.sessions.errors import SessionNotFoundError
from nestd.sessions.models import IN_FLIGHT, Session
from nestd.sessions.prompts import Choice
from nestd.sessions.store import SessionStore
from nestd.sessions.updates import save_changes

# Asks the user on a card for the run of a chat, as `SessionManager.choose` does.
type Ask = Callable[[str, dict[str, JsonValue], str], Awaitable[Choice]]
type Interrupt = Callable[[str], Awaitable[None]]
type PermissionName = Literal["accessibility", "screen_recording"]


class Permissions(Protocol):
    """The Mac's Accessibility and Screen Recording, as the helper holds them."""

    async def granted(self) -> tuple[bool, bool] | None:
        """Both answers, or None when the helper could not be asked."""
        ...

    async def ask(self, name: PermissionName) -> bool: ...


# How long an app takes to show what an action did before the screenshot after it.
SETTLE_SECONDS = 0.4
PIXIES_OFF = "Pixies may not use the computer unless the user allows it in Settings."
MASTER_OFF = "Computer use is off in Settings > Computer use."
AUTOPILOT = (
    "This chat is on Autopilot, which never uses the computer. Go on without it, or ask the"
    " user to do it."
)
# How long a card waits for the user; then it counts as no, so it never holds up the rest
# of the chat's work (D178, 2026-11-09).
ANSWER_SECONDS = 60.0
UNANSWERED = "The user did not answer within a minute, so take it as no and go on without it."


class RefusedError(Exception):
    """The call may not go ahead; the agent sees why."""


@dataclass(frozen=True)
class Frame:
    png: bytes
    target: str
    label: str
    seq: int


class ComputerStatus(BaseModel):
    enabled: bool
    kinds: list[Availability]
    # Only on a Mac: whether the helper holds each permission; None when it could not ask.
    accessibility: bool | None = None
    screen_recording: bool | None = None


def pixie_run(session: Session) -> bool:
    """Pixie chats, habit runs (they carry the pixie), chats pixies start and called pixies."""
    return (
        session.pixie_id is not None
        or session.started_by_pixie is not None
        or session.habit_run_id is not None
        or session.called_by is not None
    )


class ComputerService:
    def __init__(
        self,
        backends: Sequence[Backend],
        settings: Callable[[], ComputerUseSettings],
        store: SessionStore,
        bus: EventBus,
        ask: Ask,
        interrupt: Interrupt,
        permissions: Permissions | None = None,
        answer_seconds: float = ANSWER_SECONDS,
    ) -> None:
        self._backends = {backend.kind: backend for backend in backends}
        self._settings = settings
        self._store = store
        self._bus = bus
        self._ask = ask
        self._interrupt = interrupt
        self._permissions = permissions
        self._answer_seconds = answer_seconds
        self._locks = TargetLocks()
        self._approving = asyncio.Lock()
        self._views: dict[tuple[str, str], View] = {}
        self._frames: dict[str, Frame] = {}
        self._names: dict[str, str] = {}
        self._seq = itertools.count(1)

    # Who may use it.

    def offered(self, session: Session) -> bool:
        """Whether the chat's runs get the tools: Settings on, and for a pixie's run only
        when pixies are allowed. A chat asks the user per target when it needs one."""
        settings = self._settings()
        if not settings.enabled or session.autopilot is not None:
            return False
        return settings.pixies or not pixie_run(session)

    async def check(self, session_id: str) -> Session:
        """The chat as it is now, refused when computer use went off since its run opened."""
        session = await self._store.get(session_id)
        settings = self._settings()
        if not settings.enabled:
            raise RefusedError(MASTER_OFF)
        if pixie_run(session) and not settings.pixies:
            raise RefusedError(PIXIES_OFF)
        if session.autopilot is not None:
            raise RefusedError(AUTOPILOT)
        return session

    # What there is.

    async def status(self) -> ComputerStatus:
        kinds = [await backend.available() for backend in self._ordered()]
        granted = await self._permissions.granted() if self._permissions is not None else None
        return ComputerStatus(
            enabled=self._settings().enabled,
            kinds=kinds,
            accessibility=None if granted is None else granted[0],
            screen_recording=None if granted is None else granted[1],
        )

    async def ask_permission(self, name: PermissionName) -> bool:
        if self._permissions is None:
            msg = "Only the Mac app has these permissions."
            raise ConflictError(msg)
        return await self._permissions.ask(name)

    async def targets(self) -> tuple[list[TargetInfo], list[Availability]]:
        found: list[TargetInfo] = []
        missing: list[Availability] = []
        for backend in self._ordered():
            availability = await backend.available()
            if not availability.ready:
                missing.append(availability)
                continue
            try:
                found.extend(await backend.targets())
            except TargetError as error:
                missing.append(
                    availability.model_copy(update={"ready": False, "reason": str(error)})
                )
        for target in found:
            self._names[target.key] = target.name
        return found, missing

    def holder(self, key: str) -> str | None:
        return self._locks.holder(key)

    def frame(self, session_id: str) -> Frame | None:
        return self._frames.get(session_id)

    # Using it.

    async def open(self, session_id: str, key: str, url: str | None) -> TargetInfo:
        session = await self._ready(session_id, key)
        info = await self._backend(key).open(key, url)
        self._names[key] = info.name
        await self._announce(session.id)
        return info

    async def view(self, session_id: str, key: str, window: str | None, screenshot: bool) -> View:
        session = await self._ready(session_id, key)
        seen = await self._backend(key).view(key, window, screenshot)
        await self._keep(session.id, key, seen)
        return seen

    async def act(
        self, session_id: str, key: str, action: Action, consequential: bool
    ) -> tuple[ActResult, View | None]:
        session = await self._ready(session_id, key)
        self._require_seen(session.id, key, action)
        element = self._element(session.id, key, action)
        if action.kind in ("set_value", "type") and element is not None and is_secret(element):
            raise RefusedError(
                "That is a password or payment field. Nest never types into those: ask the"
                " user to type it themselves."
            )
        why = risk(key, action, element, consequential)
        if why is not None and not await self._confirmed(session, key, action, why):
            raise RefusedError("The user said no to this action. Ask them what to do instead.")
        backend = self._backend(key)
        try:
            done = await backend.act(key, action)
        except NeedsFrontError:
            if not await self._front_allowed(session, key):
                raise RefusedError(
                    f"{self._name(key)} must be in front for that, and the user said no."
                    " Use an element action (press, set_value) instead."
                ) from None
            await backend.front(key)
            done = await backend.act(key, action)
        if element is not None and element.label and action.element:
            # The transcript row reads this line: the element by its name, not its id.
            named = done.text.replace(action.element, f'"{_short(element.label)}"', 1)
            done = done.model_copy(update={"text": named})
        await asyncio.sleep(SETTLE_SECONDS)
        try:
            # A window the action opened, such as File > New's, is the one to look at.
            window = action.window or next((w for w, _ in done.new_windows), None)
            after = await backend.view(key, window, True)
        except TargetError:
            return done, None
        await self._keep(session.id, key, after)
        return done, after

    async def release(self, session_id: str, key: str) -> None:
        if self._locks.holder(key) == session_id:
            self._locks.release(key, session_id)
            await self._announce(session_id)

    async def release_all(self, session_id: str) -> None:
        if self._locks.release_all(session_id):
            await self._announce(session_id)

    async def stop(self, session_id: str) -> Session:
        """The user's Stop: the chat lets go of what it uses, forgets what it was allowed,
        so it asks again, and its turn stops."""
        session = await save_changes(self._store, self._bus, session_id, {"computer_targets": []})
        await self.release_all(session_id)
        await self._interrupt(session_id)
        return session

    async def state_changed(self, session: Session) -> None:
        """A turn that ended lets its targets go, so other chats may use them."""
        if session.state not in IN_FLIGHT:
            await self.release_all(session.id)

    async def purged(self, session_id: str) -> None:
        await self.release_all(session_id)
        self._frames.pop(session_id, None)
        for view in [k for k in self._views if k[0] == session_id]:
            del self._views[view]

    async def close(self) -> None:
        for backend in self._backends.values():
            await backend.close()

    # Inside.

    def _ordered(self) -> list[Backend]:
        return [self._backends[kind] for kind in KINDS if kind in self._backends]

    def _backend(self, key: str) -> Backend:
        kind = kind_of(key)
        backend = self._backends.get(kind) if kind is not None else None
        if backend is None:
            raise RefusedError(f"{key} is not a target here; computer_targets lists them.")
        return backend

    async def _ready(self, session_id: str, key: str) -> Session:
        """The chat may use `key` now: on, not held by another chat, and allowed."""
        session = await self.check(session_id)
        self._backend(key)
        if not self._locks.take(key, session.id):
            title = await self._title(self._locks.holder(key) or "")
            raise RefusedError(f"{self._name(key)} is in use by the chat {title}. Try later.")
        try:
            await self._approve(session, key)
        except RefusedError:
            await self.release(session.id, key)
            raise
        return session

    async def _approve(self, session: Session, key: str) -> None:
        if key in session.computer_targets:
            return
        # One card at a time per chat, so two quick calls do not ask twice.
        async with self._approving:
            current = await self._store.get(session.id)
            if key in current.computer_targets:
                return
            name = self._name(key)
            question = f"Let this chat use {name}?"
            payload: dict[str, JsonValue] = {
                "tool": "computer_use",
                "input": {"target": key},
                "title": question,
                "reason": None,
                "always_rule": None,
                # Allow covers this chat only: no Always allow (D178).
                "always": False,
                "computer": {"target": key, "name": name, "kind": "use"},
            }
            choice = await self._answer(session.id, payload, question)
            if choice == "deny":
                raise RefusedError(f"The user did not let this chat use {name}.")
            targets = [*current.computer_targets, key]
            await save_changes(self._store, self._bus, session.id, {"computer_targets": targets})

    async def _confirmed(self, session: Session, key: str, action: Action, why: str) -> bool:
        name = self._name(key)
        question = f"{_described(action, self._element(session.id, key, action))} in {name}?"
        frame = self._frames.get(session.id)
        payload: dict[str, JsonValue] = {
            "tool": "computer_act",
            "input": action.model_dump(mode="json", exclude_defaults=True),
            "title": question,
            "reason": why,
            "always_rule": None,
            # Asked each time: no Always allow (D178).
            "always": False,
            "computer": {
                "target": key,
                "name": name,
                "kind": "act",
                "frame": None if frame is None else frame.seq,
            },
        }
        return await self._answer(session.id, payload, question) != "deny"

    async def _front_allowed(self, session: Session, key: str) -> bool:
        name = self._name(key)
        question = f"Bring {name} to the front?"
        payload: dict[str, JsonValue] = {
            "tool": "computer_act",
            "input": {"target": key, "front": True},
            "title": question,
            "reason": "This action only works with the app in front; it takes over the screen.",
            "always_rule": None,
            "always": False,
            "computer": {"target": key, "name": name, "kind": "front"},
        }
        return await self._answer(session.id, payload, question) != "deny"

    async def _answer(
        self, session_id: str, payload: dict[str, JsonValue], question: str
    ) -> Choice:
        """The user's answer on a card; no answer in time counts as no and the card goes."""
        try:
            return await asyncio.wait_for(
                self._ask(session_id, payload, question), self._answer_seconds
            )
        except TimeoutError:
            raise RefusedError(UNANSWERED) from None

    def _require_seen(self, session_id: str, key: str, action: Action) -> None:
        """Elements and windows only from this chat's own last look at this target, so an id
        of another app's window cannot act there; typing and keys need a look first too."""
        view = self._views.get((session_id, key))
        needs_look = action.element is not None or action.kind in ("type", "key", "click")
        if view is None:
            if needs_look:
                raise RefusedError(f"Look at {self._name(key)} with computer_view first.")
            return
        if action.element is not None and all(e.id != action.element for e in view.elements):
            raise RefusedError(
                f"{action.element} is not in the last look at {self._name(key)}. Look again with"
                " computer_view."
            )
        windows = {view.window, *(w for w, _ in view.windows)}
        if action.window is not None and action.window not in windows:
            raise RefusedError(f"{action.window} is not a window of {self._name(key)}.")

    def _element(self, session_id: str, key: str, action: Action) -> Element | None:
        view = self._views.get((session_id, key))
        if view is None:
            return None
        if action.element is not None:
            return next((e for e in view.elements if e.id == action.element), None)
        # Typing and keys go to what has the keyboard.
        return next((e for e in view.elements if e.focused), None)

    async def _keep(self, session_id: str, key: str, view: View) -> None:
        self._views[(session_id, key)] = view
        if view.image is None:
            return
        frame = Frame(view.image, key, f"{self._name(key)}: {view.title}", next(self._seq))
        self._frames[session_id] = frame
        await self._bus.publish_ephemeral(
            types.COMPUTER_FRAME,
            {"target": key, "label": frame.label, "seq": frame.seq},
            session_id,
        )

    async def _announce(self, session_id: str) -> None:
        held = self._locks.held_by(session_id)
        await self._bus.publish(
            types.COMPUTER_STATE,
            {"targets": [{"key": key, "name": self._name(key)} for key in held]},
            session_id,
        )

    def _name(self, key: str) -> str:
        return self._names.get(key) or key.partition(":")[2] or key

    async def _title(self, session_id: str) -> str:
        try:
            return f'"{(await self._store.get(session_id)).title}"'
        except SessionNotFoundError:
            return "another chat"


def _short(label: str, limit: int = 60) -> str:
    flat = " ".join(label.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _described(action: Action, element: Element | None) -> str:
    """The action as the card asks it, such as `Press "Send"`."""
    label = f' "{element.label}"' if element is not None and element.label else ""
    match action.kind:
        case "press" | "click":
            return f"Press{label}" if label else "Click"
        case "menu":
            return f"Choose {' > '.join(action.menu)}"
        case "key":
            keys = "-".join(
                [*(m.capitalize() for m in action.modifiers), (action.key or "").capitalize()]
            )
            return f"Press {keys}{' in' + label if label else ''}"
        case "type":
            return f"Type into{label}" if label else "Type"
        case _:
            return f"{action.kind.replace('_', ' ').capitalize()}{label}"
