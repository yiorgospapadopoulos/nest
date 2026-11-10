"""Computer use's rules (B150, D178): off unless both switches are on, pixies kept out,
the user's Allow for each app, secret fields and one chat per app."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from pydantic import JsonValue

from nestd.autopilot.models import Autopilot
from nestd.computer.models import (
    Action,
    ActResult,
    Availability,
    Element,
    NeedsFrontError,
    TargetInfo,
    TargetKind,
    View,
    WindowFrame,
)
from nestd.computer.service import ComputerService, RefusedError
from nestd.computer.tools import computer_tools
from nestd.config.models import ComputerUseSettings
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import ToolRefusedError, ToolResult
from nestd.sessions.models import Session, SessionState
from nestd.sessions.prompts import Choice
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.fakes import FakeClock
from tests.test_session_store import new_session

KEY = "mac:com.apple.TextEdit"
PNG = b"\x89PNG\r\n\x1a\nshot"
SEND = Element(id="e2", role="AXButton", label="Send", actions=("press",))
PASSWORD = Element(id="e3", role="AXSecureTextField", secure=True)
TEXT = Element(id="e1", role="AXTextArea", label="Body", focused=True)
FIELD = Element(id="e4", role="AXTextField", label="To", field=True)
WINDOW = WindowFrame(x=100.0, y=80.0, width=586.0, height=488.0)


@dataclass
class FakeMac:
    acts: list[Action] = field(default_factory=list[Action])
    fronted: int = 0
    needs_front: bool = False

    @property
    def kind(self) -> TargetKind:
        return "mac"

    async def available(self) -> Availability:
        return Availability(kind="mac", ready=True)

    async def targets(self) -> list[TargetInfo]:
        return [TargetInfo(key=KEY, kind="mac", name="TextEdit", running=True)]

    async def open(self, key: str, url: str | None) -> TargetInfo:
        return TargetInfo(key=key, kind="mac", name="TextEdit", running=True)

    async def view(self, key: str, window: str | None, screenshot: bool) -> View:
        return View(
            title="Untitled",
            window="w1",
            elements=(TEXT, SEND, PASSWORD, FIELD),
            image=PNG if screenshot else None,
            frame=WINDOW,
        )

    async def act(self, key: str, action: Action) -> ActResult:
        if self.needs_front and action.kind == "click" and not self.fronted:
            raise NeedsFrontError("not in front")
        self.acts.append(action)
        return ActResult(text=f"Did {action.kind} {action.element} in TextEdit.")

    async def front(self, key: str) -> None:
        self.fronted += 1

    async def close(self) -> None:
        return None


@dataclass
class Cards:
    answers: list[Choice] = field(default_factory=list[Choice])
    asked: list[dict[str, JsonValue]] = field(default_factory=list[dict[str, JsonValue]])
    # Nobody answers: the card waits until it is taken away.
    silent: bool = False
    taken_away: int = 0

    async def __call__(
        self, _session_id: str, payload: dict[str, JsonValue], _notice: str
    ) -> Choice:
        self.asked.append(payload)
        if self.silent:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.taken_away += 1
                raise
        return self.answers.pop(0) if self.answers else "deny"


@dataclass
class Scene:
    service: ComputerService
    bus: EventBus
    store: SessionStore
    mac: FakeMac
    cards: Cards
    settings: list[ComputerUseSettings]
    interrupted: list[str]

    async def chat(self, **fields: object) -> Session:
        return await self.store.create(new_session(**fields))


@pytest.fixture
async def scene(db: Database, clock: FakeClock) -> Scene:
    store = SessionStore(db, clock)
    bus = EventBus(db, clock)
    mac = FakeMac()
    cards = Cards()
    settings = [ComputerUseSettings(enabled=True)]
    interrupted: list[str] = []

    async def interrupt(session_id: str) -> None:
        interrupted.append(session_id)

    service = ComputerService(
        [mac],
        settings=lambda: settings[0],
        store=store,
        bus=bus,
        ask=cards,
        interrupt=interrupt,
        answer_seconds=0.05,
    )
    return Scene(service, bus, store, mac, cards, settings, interrupted)


async def test_every_chat_gets_the_tools_while_settings_has_it_on(scene: Scene) -> None:
    chat = await scene.chat()

    assert len(computer_tools(scene.service, chat)) == 5
    scene.settings[0] = ComputerUseSettings(enabled=False)
    assert computer_tools(scene.service, chat) == ()


async def test_switching_off_in_settings_refuses_the_next_call_at_once(scene: Scene) -> None:
    chat = await scene.chat()
    scene.cards.answers = ["allow"]
    await scene.service.view(chat.id, KEY, None, True)

    scene.settings[0] = ComputerUseSettings(enabled=False)

    with pytest.raises(RefusedError, match="off in Settings"):
        await scene.service.view(chat.id, KEY, None, True)


async def test_pixie_runs_get_nothing_unless_pixies_are_allowed(scene: Scene) -> None:
    caller = await scene.chat()
    called = await scene.chat(called_by=caller.id)
    habit = caller.model_copy(update={"pixie_id": "p1"})
    started = caller.model_copy(update={"started_by_pixie": "p1"})

    assert computer_tools(scene.service, habit) == ()
    assert computer_tools(scene.service, started) == ()
    assert computer_tools(scene.service, called) == ()
    with pytest.raises(RefusedError, match="Pixies"):
        await scene.service.view(called.id, KEY, None, False)
    scene.settings[0] = ComputerUseSettings(enabled=True, pixies=True)
    assert len(computer_tools(scene.service, habit)) == 5


async def test_a_card_nobody_answers_counts_as_no_and_goes(scene: Scene) -> None:
    chat = await scene.chat()
    scene.cards.silent = True

    with pytest.raises(RefusedError, match="did not answer within a minute"):
        await scene.service.view(chat.id, KEY, None, True)

    assert scene.cards.taken_away == 1
    assert scene.service.holder(KEY) is None


async def test_a_chat_on_autopilot_never_uses_the_computer(scene: Scene) -> None:
    chat = await scene.chat()
    autopilot = Autopilot(started_at=datetime(2026, 11, 9, tzinfo=UTC), mode="default")
    on_autopilot = await scene.store.update(chat.id, autopilot=autopilot)

    assert computer_tools(scene.service, on_autopilot) == ()
    with pytest.raises(RefusedError, match="Autopilot"):
        await scene.service.view(chat.id, KEY, None, True)
    assert scene.cards.asked == []


async def test_a_pixie_called_from_a_chat_on_autopilot_never_uses_the_computer(
    scene: Scene,
) -> None:
    # B159 R05: the called pixie's card went to the caller, whose Autopilot allowed it.
    scene.settings[0] = ComputerUseSettings(enabled=True, pixies=True)
    autopilot = Autopilot(started_at=datetime(2026, 11, 9, tzinfo=UTC), mode="default")
    caller = await scene.chat()
    await scene.store.update(caller.id, autopilot=autopilot)
    called = await scene.chat(called_by=caller.id)
    scene.cards.answers = ["allow"]

    with pytest.raises(RefusedError, match="Autopilot"):
        await scene.service.view(called.id, KEY, None, True)
    assert scene.cards.asked == []


async def test_the_first_use_of_an_app_asks_and_a_no_stops_it(scene: Scene) -> None:
    chat = await scene.chat()

    with pytest.raises(RefusedError, match="did not let"):
        await scene.service.view(chat.id, KEY, None, True)

    assert scene.cards.asked[0]["title"] == f"Let this chat use {KEY.partition(':')[2]}?"
    # Allow covers this chat only: the card has no Always allow.
    assert scene.cards.asked[0]["always"] is False
    # A no lets go, so the app is free for another chat.
    assert scene.service.holder(KEY) is None


async def test_allow_is_kept_for_the_chat_only(scene: Scene) -> None:
    first = await scene.chat()
    scene.cards.answers = ["allow", "allow"]
    await scene.service.view(first.id, KEY, None, True)
    await scene.service.view(first.id, KEY, None, True)
    assert len(scene.cards.asked) == 1
    assert (await scene.store.get(first.id)).computer_targets == [KEY]

    await scene.service.release_all(first.id)
    second = await scene.chat()
    await scene.service.view(second.id, KEY, None, True)
    assert len(scene.cards.asked) == 2


async def test_once_an_app_is_allowed_nothing_more_is_asked(scene: Scene) -> None:
    scene.mac.needs_front = True
    chat = await scene.chat()
    scene.cards.answers = ["allow"]
    await scene.service.view(chat.id, KEY, None, True)

    await scene.service.act(chat.id, KEY, Action(kind="press", element="e2"))
    await scene.service.act(chat.id, KEY, Action(kind="key", key="return", element="e4"))
    await scene.service.act(chat.id, KEY, Action(kind="click", x=5, y=5))

    # Send, Return in a field and a click that brings the app forward all go ahead.
    assert len(scene.cards.asked) == 1
    # Clients knew it was in use from the first step, then where its window is, for the
    # glow on that screen.
    events = await scene.bus.session_events(chat.id)
    states = [e.payload for e in events if e.type == types.COMPUTER_STATE]
    assert states[0] == {"targets": [{"key": KEY, "name": "com.apple.TextEdit", "frame": None}]}
    assert states[1] == {
        "targets": [{"key": KEY, "name": "com.apple.TextEdit", "frame": WINDOW.model_dump()}]
    }
    assert [a.kind for a in scene.mac.acts] == ["press", "key", "click"]
    assert scene.mac.fronted == 1


async def test_secret_fields_are_never_typed_into(scene: Scene) -> None:
    chat = await scene.chat()
    scene.cards.answers = ["allow"]
    await scene.service.view(chat.id, KEY, None, True)

    with pytest.raises(RefusedError, match="password"):
        await scene.service.act(
            chat.id, KEY, Action(kind="set_value", element="e3", text="hunter2")
        )
    assert scene.mac.acts == []


async def test_one_chat_holds_an_app_until_its_turn_ends(scene: Scene) -> None:
    first = await scene.chat()
    second = await scene.chat(title="Other")
    scene.cards.answers = ["allow", "allow"]
    await scene.service.view(first.id, KEY, None, True)

    with pytest.raises(RefusedError, match='in use by the chat "Fix it"'):
        await scene.service.view(second.id, KEY, None, True)

    await scene.service.state_changed(await scene.store.update(first.id, state=SessionState.IDLE))
    await scene.service.view(second.id, KEY, None, True)
    assert scene.service.holder(KEY) == second.id


async def test_only_what_the_chat_saw_of_this_app_can_be_acted_on(scene: Scene) -> None:
    chat = await scene.chat()
    scene.cards.answers = ["allow"]

    with pytest.raises(RefusedError, match="computer_view first"):
        await scene.service.act(chat.id, KEY, Action(kind="type", text="hi"))
    await scene.service.view(chat.id, KEY, None, False)
    # An id from another app's window, or one not in the last look, does nothing.
    with pytest.raises(RefusedError, match="not in the last look"):
        await scene.service.act(chat.id, KEY, Action(kind="press", element="e99"))
    with pytest.raises(RefusedError, match="not a window"):
        await scene.service.act(chat.id, KEY, Action(kind="press", element="e1", window="w7"))
    assert scene.mac.acts == []


async def test_stop_lets_go_stops_the_turn_and_asks_again_next_time(scene: Scene) -> None:
    chat = await scene.chat()
    scene.cards.answers = ["allow", "deny"]
    await scene.service.view(chat.id, KEY, None, True)

    stopped = await scene.service.stop(chat.id)

    assert stopped.computer_targets == []
    assert scene.service.holder(KEY) is None
    assert scene.interrupted == [chat.id]
    with pytest.raises(RefusedError, match="did not let"):
        await scene.service.view(chat.id, KEY, None, True)
    assert len(scene.cards.asked) == 2


async def test_an_action_returns_a_fresh_screenshot_to_the_agent(scene: Scene) -> None:
    chat = await scene.chat()
    scene.cards.answers = ["allow"]
    act = next(t for t in computer_tools(scene.service, chat) if t.name == "computer_act")
    await scene.service.view(chat.id, KEY, None, False)

    result = await act.handler({"target": KEY, "action": "press", "element": "e1"})

    assert isinstance(result, ToolResult)
    assert result.images == (PNG,)
    # The element by its name, which the transcript row shows.
    assert result.text.startswith('Did press "Body" in TextEdit.')
    assert scene.service.frame(chat.id) is not None
    with pytest.raises(ToolRefusedError):
        await act.handler({"target": "nowhere:x", "action": "press"})
