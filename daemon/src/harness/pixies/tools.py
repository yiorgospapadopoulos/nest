"""The tools every pixie run has: its memory, notes, soul and project list (D072).

Each handler re-reads the file it changes, so a write never loses a change the user
saved meanwhile.
"""

from collections.abc import Awaitable, Callable

from pydantic import JsonValue

from harness.clock import Clock
from harness.errors import HarnessError
from harness.pixies.files import PixieFiles
from harness.pixies.models import Pixie
from harness.providers.base import AgentTool, ToolRefusedError
from harness.repos.service import RepoService

TOOL_NAMES = (
    "memory_read",
    "memory_write",
    "memory_forget",
    "notes_search",
    "note_read",
    "note_write",
    "soul_read",
    "soul_write",
    "list_projects",
)

type Handler = Callable[[dict[str, JsonValue]], Awaitable[str]]


def _schema(**fields: str) -> dict[str, JsonValue]:
    return {
        "type": "object",
        "properties": {name: {"type": "string", "description": d} for name, d in fields.items()},
        "required": list(fields),
    }


def _text(args: dict[str, JsonValue], name: str) -> str:
    return str(args.get(name, ""))


def pixie_tools(
    pixie: Pixie, files: PixieFiles, repos: RepoService, clock: Clock
) -> tuple[AgentTool, ...]:
    pid = pixie.id

    def refusing(handler: Handler) -> Handler:
        async def wrapped(args: dict[str, JsonValue]) -> str:
            try:
                return await handler(args)
            except HarnessError as error:
                raise ToolRefusedError(str(error)) from error

        return wrapped

    async def memory_read(_args: dict[str, JsonValue]) -> str:
        return files.read(pid, "memory").text

    async def memory_write(args: dict[str, JsonValue]) -> str:
        saved = files.add_fact(pid, _text(args, "fact"), clock.now().date())
        return f"Saved: {saved.text.splitlines()[-1]}"

    async def memory_forget(args: dict[str, JsonValue]) -> str:
        text = _text(args, "text")
        if not text.strip():
            raise ToolRefusedError("Say which fact to forget.")
        removed = files.forget(pid, text)
        if removed == 0:
            return "No fact matched."
        return f"Forgot {removed} fact." if removed == 1 else f"Forgot {removed} facts."

    async def notes_search(args: dict[str, JsonValue]) -> str:
        query = _text(args, "query")
        if not query.strip():
            raise ToolRefusedError("Say what to search for.")
        hits = files.search(pid, query)
        return "\n".join(f"{h.file}: {h.line}" for h in hits) or "Nothing found."

    async def note_read(args: dict[str, JsonValue]) -> str:
        return files.read(pid, f"notes/{_text(args, 'name')}").text

    async def note_write(args: dict[str, JsonValue]) -> str:
        name = f"notes/{_text(args, 'name')}"
        # Safe only because nothing awaits between this read and the write below.
        try:
            current: str | None = files.read(pid, name).hash
        except HarnessError:
            current = None
        files.write(pid, name, _text(args, "text"), current)
        return f"Saved {name}.md."

    async def soul_read(_args: dict[str, JsonValue]) -> str:
        return files.read(pid, "soul").text

    async def soul_write(args: dict[str, JsonValue]) -> str:
        # Safe only because nothing awaits between this read and the write below.
        files.write(pid, "soul", _text(args, "text"), files.read(pid, "soul").hash)
        return "Saved SOUL.md."

    async def list_projects(_args: dict[str, JsonValue]) -> str:
        projects = sorted(repos.list_repos(), key=lambda repo: repo.name)
        if pixie.projects is not None:
            projects = [repo for repo in projects if repo.name in pixie.projects]
        return "\n".join(f"{repo.name}: {repo.path}" for repo in projects) or "No projects."

    specs: list[tuple[str, str, dict[str, JsonValue], Handler]] = [
        (
            "memory_read",
            "Read MEMORY.md, your saved facts and preferences.",
            _schema(),
            memory_read,
        ),
        (
            "memory_write",
            "Save one durable fact or preference to MEMORY.md (dated automatically). "
            "Never save secrets.",
            _schema(fact="The fact, one line."),
            memory_write,
        ),
        (
            "memory_forget",
            "Remove every fact in MEMORY.md containing the text (case-insensitive).",
            _schema(text="Text the facts to remove contain."),
            memory_forget,
        ),
        (
            "notes_search",
            "Search MEMORY.md, your notes and your archive of older facts.",
            _schema(query="Text to look for (case-insensitive)."),
            notes_search,
        ),
        ("note_read", "Read one of your notes.", _schema(name="The note's name."), note_read),
        (
            "note_write",
            "Create or replace one of your notes, for longer topics than a fact.",
            _schema(name="Lowercase letters, digits and dashes.", text="The note's Markdown."),
            note_write,
        ),
        ("soul_read", "Read SOUL.md, your standing instructions.", _schema(), soul_read),
        (
            "soul_write",
            "Replace SOUL.md. Only when the user asks you to change your instructions.",
            _schema(text="The whole new SOUL.md."),
            soul_write,
        ),
        (
            "list_projects",
            "List the projects you are assigned to, one per line as name: folder.",
            _schema(),
            list_projects,
        ),
    ]
    return tuple(AgentTool(name, desc, schema, refusing(h)) for name, desc, schema, h in specs)
