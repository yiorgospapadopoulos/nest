"""A pixie's report and habit tools (B42), at every autonomy level, in its chat's runs and
its habit runs. The habit tools reach only the pixie's own habits and are logged in its
activity.
"""

from collections.abc import Awaitable, Callable

from pydantic import JsonValue, ValidationError

from nestd.errors import NestError
from nestd.pixies.activity import ActivityStore
from nestd.pixies.habit_models import (
    BODY_MAX,
    LINK_MAX,
    SEVERITIES,
    TITLE_MAX,
    TRIGGERS,
    CreateHabit,
    Habit,
    Severity,
    UpdateHabit,
    problems,
)
from nestd.pixies.habit_store import HabitStore
from nestd.pixies.habits import HabitService
from nestd.pixies.reporting import FromRun, Reports
from nestd.pixies.schedule import describe
from nestd.providers.base import AgentTool, ToolRefusedError
from nestd.sessions.models import Session
from nestd.tracking.steps import one_line

REPORT_TOOL_NAMES = ("report", "habit_list", "habit_create", "habit_update", "habit_pause")
SUMMARY_CHARS = 120

type Args = dict[str, JsonValue]
type Handler = Callable[[Args], Awaitable[str]]

SCHEDULE: dict[str, JsonValue] = {
    "type": "object",
    "description": 'When it runs, in the Mac\'s local time: {"kind": "hourly", "minute": 0-59},'
    ' {"kind": "daily", "time": "HH:MM"}, {"kind": "weekdays", "time": "HH:MM"} (Monday to'
    ' Friday) or {"kind": "weekly", "weekday": 0-6 (Monday is 0), "time": "HH:MM"}.',
}
TRIGGER_LIST: dict[str, JsonValue] = {
    "type": "array",
    "items": {"type": "string", "enum": list(TRIGGERS)},
    "description": "Events on chats in your projects that run it: a chat looks stuck,"
    " failed, is ready for review, or its pull request's checks failed. Events are"
    " batched; it runs at most once in 5 minutes.",
}
HABIT_FIELDS: dict[str, JsonValue] = {
    "name": {"type": "string", "description": "A short name, at most 60 characters."},
    "prompt": {
        "type": "string",
        "description": "What to check and what is worth reporting, at most 4000 characters.",
    },
    "schedule": SCHEDULE,
    "triggers": TRIGGER_LIST,
    "max_minutes": {
        "type": "integer",
        "description": "How long a run may take, 1 to 120 minutes (default 20).",
    },
}


class PixieHabitTools:
    """What a pixie's report and habit tools act through; one per daemon."""

    def __init__(
        self, *, habits: HabitService, store: HabitStore, reports: Reports, activity: ActivityStore
    ) -> None:
        self.habits = habits
        self.store = store
        self.reports = reports
        self.activity = activity

    def tools(self, pixie_id: str, session: Session) -> tuple[AgentTool, ...]:
        """The tools of a run of `session`: the pixie's chat, or one of its habit runs."""
        return _Tools(self, pixie_id, session).all()


class _Tools:
    def __init__(self, owner: PixieHabitTools, pixie_id: str, session: Session) -> None:
        self._o = owner
        self._pixie_id = pixie_id
        self._session = session

    def all(self) -> tuple[AgentTool, ...]:
        specs: list[tuple[str, str, dict[str, JsonValue], Handler]] = [
            (
                "report",
                "Tell the user something worth knowing. It shows as a card in your chat;"
                " warn and action also in the inbox, and by your phone alert setting on the"
                " user's phone (action: needs the user). From a habit run, your chat then"
                " gets a turn about it.",
                {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": list(SEVERITIES)},
                        "title": {
                            "type": "string",
                            "description": f"One line, at most {TITLE_MAX} characters.",
                        },
                        "body": {
                            "type": "string",
                            "description": f"The details, at most {BODY_MAX} characters.",
                        },
                        "link": {"type": "string", "description": "An optional http(s) link."},
                    },
                    "required": ["severity", "title"],
                },
                self.report,
            ),
            (
                "habit_list",
                "List your habits: id | name | schedule | triggers | state | last run.",
                {"type": "object", "properties": {}, "required": []},
                self.habit_list,
            ),
            (
                "habit_create",
                "Create one of your habits, enabled: a prompt you run in the background on a"
                " schedule, on events, or both, speaking only through report.",
                {
                    "type": "object",
                    "properties": HABIT_FIELDS,
                    "required": ["name", "prompt"],
                },
                self.habit_create,
            ),
            (
                "habit_update",
                "Change one of your habits; fields left out stay. A null schedule removes it.",
                {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "From habit_list."},
                        **HABIT_FIELDS,
                    },
                    "required": ["id"],
                },
                self.habit_update,
            ),
            (
                "habit_pause",
                "Pause one of your habits, or resume it.",
                {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "From habit_list."},
                        "paused": {"type": "boolean", "description": "false resumes it."},
                    },
                    "required": ["id", "paused"],
                },
                self.habit_pause,
            ),
        ]
        return tuple(
            AgentTool(name, desc, schema, _guarded(fn)) for name, desc, schema, fn in specs
        )

    async def report(self, args: Args) -> str:
        severity = _severity(args.get("severity"))
        title = _text(args, "title", TITLE_MAX)
        body = _optional_text(args, "body", BODY_MAX) or ""
        link = _optional_text(args, "link", LINK_MAX)
        if link is not None and not link.startswith(("https://", "http://")):
            msg = "link must start with https:// or http://."
            raise ToolRefusedError(msg)
        run_id = self._session.habit_run_id
        if run_id is None:
            source: str | FromRun = self._session.id
        else:
            run = await self._o.store.run(run_id)
            if run is None:
                msg = "This habit run is over; its habit was deleted."
                raise ToolRefusedError(msg)
            habit = await self._o.store.get(run.habit_id)
            source = FromRun(run.id, habit.id, habit.name)
        await self._o.reports.report(self._pixie_id, severity, title, body, link, source)
        return "Reported."

    async def habit_list(self, args: Args) -> str:
        habits = await self._o.habits.list_habits(self._pixie_id)
        if not habits:
            return "You have no habits."
        return "\n".join(_line(habit) for habit in habits)

    async def habit_create(self, args: Args) -> str:
        try:
            request = CreateHabit.model_validate(args)
        except ValidationError as error:
            raise ToolRefusedError(problems(error)) from error
        habit = await self._o.habits.create(self._pixie_id, request)
        await self._log("habit_create", f'Created habit "{habit.name}"')
        return f"Created habit {habit.id}: {_line(habit)}"

    async def habit_update(self, args: Args) -> str:
        habit_id = _text(args, "id")
        try:
            request = UpdateHabit.model_validate({k: v for k, v in args.items() if k != "id"})
        except ValidationError as error:
            raise ToolRefusedError(problems(error)) from error
        habit = await self._o.habits.update(self._pixie_id, habit_id, request)
        await self._log("habit_update", f'Changed habit "{habit.name}"')
        return f"Changed: {_line(habit)}"

    async def habit_pause(self, args: Args) -> str:
        habit_id = _text(args, "id")
        paused = args.get("paused")
        if not isinstance(paused, bool):
            msg = "paused must be true or false."
            raise ToolRefusedError(msg)
        habit = await self._o.habits.update(
            self._pixie_id, habit_id, UpdateHabit(enabled=not paused)
        )
        done = "Paused" if paused else "Resumed"
        await self._log("habit_pause", f'{done} habit "{habit.name}"')
        return f"{done}: {_line(habit)}"

    async def _log(self, tool: str, summary: str) -> None:
        await self._o.activity.add(self._pixie_id, tool, None, one_line(summary, SUMMARY_CHARS))


def _line(habit: Habit) -> str:
    schedule = "no schedule" if habit.schedule is None else describe(habit.schedule)
    triggers = ", ".join(habit.triggers) or "none"
    state = "on" if habit.enabled else "paused"
    last = habit.last_run
    ran = "never run" if last is None else f"last run {last.outcome}"
    return f"{habit.id} | {habit.name} | {schedule} | triggers: {triggers} | {state} | {ran}"


def _guarded(handler: Handler) -> Handler:
    async def run(args: Args) -> str:
        try:
            return await handler(args)
        except NestError as error:
            raise ToolRefusedError(str(error)) from error

    return run


def _severity(value: JsonValue) -> Severity:
    for severity in SEVERITIES:
        if value == severity:
            return severity
    msg = f"severity must be one of: {', '.join(SEVERITIES)}."
    raise ToolRefusedError(msg)


def _text(args: Args, name: str, limit: int | None = None) -> str:
    value = _optional_text(args, name, limit)
    if value is None:
        msg = f"{name} is required."
        raise ToolRefusedError(msg)
    return value


def _optional_text(args: Args, name: str, limit: int | None = None) -> str | None:
    value = args.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{name} must be text."
        raise ToolRefusedError(msg)
    value = value.strip()
    if limit is not None and len(value) > limit:
        msg = f"{name} is too long: at most {limit} characters."
        raise ToolRefusedError(msg)
    return value or None
