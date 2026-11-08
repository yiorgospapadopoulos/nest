"""The computer-use tools a chat's runs get while its computer use is on (B150), the same
on every engine."""

from collections.abc import Awaitable
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from nestd.computer.models import ACTION_KINDS, TOOL_NAMES, Action, TargetError, View, outline
from nestd.computer.service import ComputerService, RefusedError
from nestd.providers.base import AgentTool, ToolRefusedError, ToolResult
from nestd.sessions.models import Session

TARGETS, OPEN, VIEW, ACT, RELEASE = TOOL_NAMES

GUIDE = (
    "Work in the background: read the window's elements with computer_view and act on them"
    " by id (press, set_value, menu, type, key); coordinate clicks need the app in front and"
    " ask the user first. Never type passwords or payment details: ask the user to. Before"
    " anything that sends, submits, buys, deletes or changes settings, set consequential"
    " true. When done with a target, call computer_release."
)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Open(_Args):
    target: str
    url: str | None = None


class _View(_Args):
    target: str
    window: str | None = None
    screenshot: bool = True


class _Act(_Args):
    target: str
    action: Literal[
        "press", "set_value", "type", "key", "menu", "scroll", "click", "focus", "navigate"
    ]
    element: str | None = None
    text: str | None = None
    key: str | None = None
    modifiers: list[Literal["cmd", "shift", "option", "control"]] = []
    menu: list[str] = []
    direction: Literal["up", "down", "left", "right"] | None = None
    amount: int = 3
    x: int | None = None
    y: int | None = None
    url: str | None = None
    window: str | None = None
    consequential: bool = False


class _Release(_Args):
    target: str


def computer_tools(service: ComputerService, session: Session) -> tuple[AgentTool, ...]:
    """The tools, or none when computer use is off in Settings or it is a pixie's run that
    may not use it."""
    if not service.offered(session):
        return ()

    async def targets(_: dict[str, JsonValue]) -> str:
        found, missing = await _refusing(service.targets())
        lines = [
            f"{t.key}: {t.name}{'' if t.running else ' (not running)'}"
            + _held(service, t.key, session.id)
            for t in found
        ]
        lines += [f"({a.kind}: {a.reason})" for a in missing if a.reason]
        return "\n".join(lines) or "Nothing to use here."

    async def open_target(args: dict[str, JsonValue]) -> str:
        request = _parsed(_Open, args)
        info = await _refusing(service.open(session.id, request.target, request.url))
        return f"{info.name} is open in the background. Look at it with {VIEW}."

    async def view(args: dict[str, JsonValue]) -> ToolResult:
        request = _parsed(_View, args)
        seen = await _refusing(
            service.view(session.id, request.target, request.window, request.screenshot)
        )
        return _result(outline(seen), seen)

    async def act(args: dict[str, JsonValue]) -> ToolResult:
        request = _parsed(_Act, args)
        action = _parsed_action(request)
        done, after = await _refusing(
            service.act(session.id, request.target, action, request.consequential)
        )
        return _result(done.text if after is None else f"{done.text}\n{outline(after)}", after)

    async def release(args: dict[str, JsonValue]) -> str:
        request = _parsed(_Release, args)
        await service.release(session.id, request.target)
        return f"Let go of {request.target}."

    target: JsonValue = {"type": "string", "description": "A target key from computer_targets."}
    return (
        AgentTool(
            TARGETS,
            "List what this chat can see and use: Mac apps (mac:<bundle id>), iOS Simulator"
            " devices (ios:<udid>), Android emulators (android:<serial>) and Nest's shared"
            f" browser (browser). {GUIDE}",
            {"type": "object", "properties": {}},
            targets,
        ),
        AgentTool(
            OPEN,
            "Open a target in the background: launch the app, boot the simulator, start the"
            " emulator or open the shared browser, optionally at a link.",
            {
                "type": "object",
                "properties": {"target": target, "url": {"type": "string"}},
                "required": ["target"],
            },
            open_target,
        ),
        AgentTool(
            VIEW,
            "Look at a target's window: its elements with ids to act on, and a screenshot."
            " Without window, the first one Nest can see.",
            {
                "type": "object",
                "properties": {
                    "target": target,
                    "window": {"type": "string"},
                    "screenshot": {"type": "boolean"},
                },
                "required": ["target"],
            },
            view,
        ),
        AgentTool(
            ACT,
            "Do one thing in a target, then get a fresh screenshot. press, focus, set_value"
            " (element, text), type (text, to what has the keyboard or element), key (key such"
            " as return, tab, escape, a; modifiers), menu (menu path such as"
            ' ["File", "New"]), scroll (direction, amount), click (x, y in screenshot pixels;'
            " last resort), navigate (url; browser and devices).",
            {
                "type": "object",
                "properties": {
                    "target": target,
                    "action": {"type": "string", "enum": [*ACTION_KINDS]},
                    "element": {"type": "string"},
                    "text": {"type": "string"},
                    "key": {"type": "string"},
                    "modifiers": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["cmd", "shift", "option", "control"]},
                    },
                    "menu": {"type": "array", "items": {"type": "string"}},
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                    "amount": {"type": "integer"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "url": {"type": "string"},
                    "window": {"type": "string"},
                    "consequential": {
                        "type": "boolean",
                        "description": "True when it sends, submits, buys, deletes or changes"
                        " settings: the user is asked first.",
                    },
                },
                "required": ["target", "action"],
            },
            act,
        ),
        AgentTool(
            RELEASE,
            "Let go of a target when done, so other chats may use it.",
            {"type": "object", "properties": {"target": target}, "required": ["target"]},
            release,
        ),
    )


def _result(text: str, view: View | None) -> ToolResult:
    return ToolResult(text, () if view is None or view.image is None else (view.image,))


def _held(service: ComputerService, key: str, session_id: str) -> str:
    holder = service.holder(key)
    return "" if holder in (None, session_id) else " (in use by another chat)"


def _parsed_action(request: _Act) -> Action:
    try:
        return Action(
            kind=request.action,
            element=request.element,
            text=request.text,
            key=request.key,
            modifiers=tuple(request.modifiers),
            menu=tuple(request.menu),
            direction=request.direction,
            amount=request.amount,
            x=request.x,
            y=request.y,
            url=request.url,
            window=request.window,
        )
    except ValidationError as error:
        raise ToolRefusedError(_problems(error)) from None


def _parsed[M: _Args](model: type[M], args: dict[str, JsonValue]) -> M:
    try:
        return model.model_validate(args)
    except ValidationError as error:
        raise ToolRefusedError(_problems(error)) from None


def _problems(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in issue['loc']) or 'input'}: {issue['msg']}"
        for issue in error.errors()
    )


async def _refusing[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except (RefusedError, TargetError) as error:
        raise ToolRefusedError(str(error)) from None
