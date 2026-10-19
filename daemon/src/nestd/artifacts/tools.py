"""The artifact tools every chat and pixie run gets (B79). A run's tools act for its chat:
what a subagent saves belongs to the chat too.
"""

import json
from collections.abc import Awaitable
from importlib.resources import files

from pydantic import BaseModel, JsonValue, ValidationError

from nestd.artifacts.files import FILES_MAX, VERSION_MAX
from nestd.artifacts.kinds import (
    COLORS_MAX,
    COMPONENT_HTML_MAX,
    DESCRIPTION_MAX,
    ENTRIES_MAX,
    INTRO_MAX,
    NAME_MAX,
    SCREEN_HTML_MAX,
    SCREENS_MAX,
    SLIDES_MAX,
    URL_MAX,
)
from nestd.artifacts.models import (
    CONTENT_MAX,
    KINDS,
    TITLE_MAX,
    ArtifactKind,
    Origin,
)
from nestd.artifacts.service import Artifacts, ReadArtifact
from nestd.artifacts.storage import KEYS_MAX, STORAGE_MAX, VALUE_MAX
from nestd.config.models import ArtifactSettings
from nestd.errors import NestError
from nestd.pixies.habit_models import problems
from nestd.providers.base import AgentTool, ToolRefusedError
from nestd.sessions.models import Session

CREATE_ARTIFACT = "create_artifact"
UPDATE_ARTIFACT = "update_artifact"
READ_ARTIFACT = "read_artifact"
ARTIFACT_GUIDE = "artifact_guide"

# Nest's design guidance for pages, designs and design systems (B88).
GUIDE = files("nestd.artifacts").joinpath("guide.md").read_text(encoding="utf-8")

# The exact shapes, since agents otherwise guess them (B88 live checks).
USAGE_SHAPE = (
    "await nest.usage() returns {limits: {five_hour: {utilization: a fraction 0 to 1 (0.42 is"
    " 42%), resets_at: ISO time} or null, seven_day: same}, today: {tokens, sessions}, week:"
    " {tokens, sessions}}; there are no token limits, only how full each window is;"
    " nest.onUsage(fn) gets the same object on changes."
)
ASK_SHAPE = (
    "await nest.ask(prompt, {system}) returns {text, remaining, limit}; errors have .code"
    " budget, busy, disabled or unavailable."
)

# What a page may do: the clients' page policy (D110) allows these hosts and nothing else;
# links go through the bridge (D115).
_RULES = (
    "Markdown supports tables, Mermaid diagrams (```mermaid blocks) and code blocks. An HTML"
    " page may load scripts only from cdnjs.cloudflare.com, cdn.jsdelivr.net/npm/, unpkg.com,"
    " cdn.tailwindcss.com and code.jquery.com, and stylesheets and fonts only from Google"
    " Fonts, each with an exact version (react@18.3.1, never react or react@18); everything"
    " else inline or in files, images as data: URIs or files, and no fetch or forms."
    " To remember what the user enters, use localStorage as you normally would"
    " (localStorage.getItem/setItem work as usual; Nest keeps it, shared across the user's"
    f" devices; at most {KEYS_MAX} keys, {VALUE_MAX // 1024} KiB a value,"
    f" {STORAGE_MAX // 1024 // 1024} MiB a page); window.nest.storage offers the same with"
    " get/set and onChange for changes from the user's other devices. <input type=file>"
    " works, and a page may keep a picked file's content in storage within those caps;"
    " window.nest.saveFile({name, content, encoding, mime}) offers a file to save."
    f" {USAGE_SHAPE} {ASK_SHAPE} Ask Claude only for small text tasks (at most"
    f" {ArtifactSettings().ask_daily_limit} a day per artifact by default, short answers, no"
    " tools): only when the user does something, never on load or in a loop, and show the"
    " answer as text, not HTML. Links are plain"
    ' <a href="https://...">: Nest asks the user and opens them in the browser; #anchors work'
    " inside the page, and window.nest.openLink(url) does the same from script. For"
    " React, load React, ReactDOM and Babel standalone from these hosts with"
    ' <script type="text/babel">. Define colors as CSS variables with a prefers-color-scheme:'
    " dark block and an explicit body background (canvas charts (Chart.js) need real colors,"
    " read with getComputedStyle, not var() strings), fit phone width with no sideways scroll,"
    " and set a short <title>."
)

# The data of each kind (D116): Nest builds the page of the ready-made kinds from it.
_FORMATS = (
    "By kind. markdown: Markdown. document: Markdown for a long read; Nest adds a table of"
    " contents from its ## and ### headings, and the user may edit its ## sections in the"
    " reader. slides: Markdown, one slide per part, parts separated by a line that is exactly"
    f" ---; {SLIDES_MAX} slides at most, none empty, each fitting a 16:9 slide. design: JSON"
    " (not HTML), mockups presented for a decision:"
    ' {"intro": "what is being decided, in 2 to 4 sentences", "layout": "stack", "screens":'
    ' [{"label": "A", "title": "Start screen", "description": "its idea and trade-off",'
    ' "device": "phone", "frame": "auto", "url": "optional", "html":'
    ' "<style>...</style><main>...</main>"}]}: intro Markdown up to'
    f" {INTRO_MAX} characters; layout stack for full screens (the default), grid for many small"
    " designs or elements, tabs when options are big and best compared one at a time, or"
    " canvas; label 1 to 3 letters or digits (A, B, C or 1, 2, 3); title at most"
    f" {NAME_MAX} characters; description optional Markdown up to {DESCRIPTION_MAX} characters,"
    " the option's idea and trade-off in one or two sentences; device phone, tablet, desktop or"
    " square; frame window for Mac apps, browser for websites (url, up to"
    f" {URL_MAX} characters, shows in its address bar), phone or tablet for mobile bezels, none"
    " only if the html draws its own chrome, or auto; 1 to"
    f" {SCREENS_MAX} screens, each html at most {SCREEN_HTML_MAX // 1024} KB. Use real content."
    " End your chat reply by asking the user to answer with a label. For live 3D or animated"
    " pieces make an html page laid out the same way (an intro, then labelled items with a"
    " title and description), since design screens are static. design_system: JSON"
    ' {"name": "...", "description": "optional", "colors": [{"name": "accent", "light":'
    ' "#4C6EF5", "dark": "optional", "role": "optional"}], "typography": [{"name": "Title",'
    ' "family": "...", "size": 28, "weight": 700, "line_height": 1.2, "sample": "optional"}],'
    ' "spacing": [{"name": "s", "value": 8}], "radii": [{"name": "card", "value": 16}],'
    ' "components": [{"name": "...", "html": "...", "description": "optional"}]}: colors hex'
    f" #rgb, #rrggbb or #rrggbbaa, 1 to {COLORS_MAX} colors, at most {ENTRIES_MAX} of each"
    f" other list, each component html at most {COMPONENT_HTML_MAX // 1024} KB. Design screens"
    " and components are static: each renders in its own shadow root, :root in its CSS"
    " becomes :host, and its scripts and on* attributes are removed. For these four kinds send"
    f" only the data, never a page. html: a whole page you write. {_RULES}"
)

# For the system prompts of chats and pixies.
ARTIFACT_NOTE = (
    "To give the user a long report, summary, comparison or plan, save it as an artifact "
    "with create_artifact instead of a long chat message or a file in the repository, then "
    "reply briefly. Pick the kind: a report as a document, a deck as slides, mockups before "
    "a design change as a design with 2 to 4 variants (A, B, C), tokens and components as a "
    "design_system, html for anything interactive such as a chart or small app, markdown "
    "for short notes. Call artifact_guide once before making an html page, a design or a "
    "design_system. update_artifact saves a new version of one you created; call "
    "read_artifact first when the user may have edited it."
)

_CONTENT: dict[str, JsonValue] = {
    "type": "string",
    "description": f"The whole content, at most {CONTENT_MAX} bytes, shown sandboxed. {_FORMATS}",
}
_TITLE: dict[str, JsonValue] = {
    "type": "string",
    "description": f"A short title, at most {TITLE_MAX} characters.",
}
_ID: dict[str, JsonValue] = {"type": "string"}
_FILES: dict[str, JsonValue] = {
    "type": "array",
    "description": (
        f"Only for kind html: the files of a multi-file page, at most {FILES_MAX} and"
        f" {VERSION_MAX // 1024 // 1024} MiB with the page. Paths are relative (letters, digits,"
        " . _ - and /). The page names them with relative src and href (scripts, stylesheets,"
        " images, url() in CSS), which Nest inlines, and reads any of them with"
        " window.nest.files (list, text, dataUrl, blobUrl). A version has only the files sent"
        " with it: an update without files has none, so send them all again."
    ),
    "items": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "encoding": {"type": "string", "enum": ["utf8", "base64"]},
        },
        "required": ["path", "content"],
    },
}
# Of what a page stored, read_artifact shows this many characters of JSON at most.
_STORED_SHOWN = 20 * 1024


class _Create(BaseModel):
    title: str
    kind: ArtifactKind
    content: str
    files: list[dict[str, JsonValue]] | None = None


class _Update(BaseModel):
    artifact_id: str
    content: str
    title: str | None = None
    files: list[dict[str, JsonValue]] | None = None


class _Read(BaseModel):
    artifact_id: str


def artifact_tools(artifacts: Artifacts, session: Session) -> tuple[AgentTool, ...]:
    origin = Origin(
        session_id=session.id,
        repo=session.repo,
        chat_title=session.title,
        pixie_id=session.pixie_id,
    )

    async def create(args: dict[str, JsonValue]) -> str:
        request = _parsed(_Create, args)
        artifact = await _refusing(
            artifacts.create(origin, request.kind, request.title, request.content, request.files)
        )
        return (
            f"Saved artifact {artifact.id} (version 1): {artifact.title}. The user opens it"
            " from the card in this chat; to change it, call update_artifact with this id."
        )

    async def update(args: dict[str, JsonValue]) -> str:
        request = _parsed(_Update, args)
        artifact = await _refusing(
            artifacts.update(
                origin, request.artifact_id, request.content, request.title, request.files
            )
        )
        return (
            f"Saved version {artifact.latest_version} of artifact {artifact.id}: {artifact.title}."
        )

    async def read(args: dict[str, JsonValue]) -> str:
        request = _parsed(_Read, args)
        return _described(await _refusing(artifacts.read(origin, request.artifact_id)))

    async def guide(_: dict[str, JsonValue]) -> str:
        return GUIDE

    return (
        AgentTool(
            CREATE_ARTIFACT,
            "Save an artifact the user opens in Nest's reader: a document (report, plan),"
            " slides (a deck), a design (mockups in variants), a design system, Markdown notes"
            " or an HTML page such as a chart or small app. Returns its id.",
            {
                "type": "object",
                "properties": {
                    "title": _TITLE,
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "content": _CONTENT,
                    "files": _FILES,
                },
                "required": ["title", "kind", "content"],
            },
            create,
        ),
        AgentTool(
            UPDATE_ARTIFACT,
            "Save a new version of an artifact this chat created, of the same kind; earlier"
            " versions are kept. The user may have edited a document: read_artifact first.",
            {
                "type": "object",
                "properties": {
                    "artifact_id": _ID,
                    "content": _CONTENT,
                    "title": {**_TITLE, "description": "A new title; left out keeps the title."},
                    "files": _FILES,
                },
                "required": ["artifact_id", "content"],
            },
            update,
        ),
        AgentTool(
            READ_ARTIFACT,
            "Read the latest version of an artifact this chat created: its kind, version, who"
            " saved it (an agent, or the user editing it in the reader), its files, its content"
            " and what its page stored (such as a tracker's entries).",
            {
                "type": "object",
                "properties": {"artifact_id": _ID},
                "required": ["artifact_id"],
            },
            read,
        ),
        AgentTool(
            ARTIFACT_GUIDE,
            "Nest's design guidance for artifacts: layout, type, colour, motion, charts, phone"
            " width and how to mock up a design. Read it once before making an html page, a"
            " design or a design system.",
            {"type": "object", "properties": {}},
            guide,
        ),
    )


def _described(read: ReadArtifact) -> str:
    latest, stored = read.latest, read.stored
    author = "the user (edited in Nest's reader)" if latest.author == "user" else "an agent"
    lines = [
        f"Artifact {latest.artifact_id}: {latest.title}",
        f"Kind: {latest.kind}. Latest version: {latest.version}, saved by {author}.",
    ]
    if latest.files:
        listed = ", ".join(f"{f.path} ({f.size} bytes, {f.mime})" for f in latest.files)
        lines.append(f"Files: {listed}.")
    if read.asks.used:
        lines.append(f"Asks of Claude today: {read.asks.used} of {read.asks.limit}.")
    if not stored.items:
        lines.append("Stored by its page: nothing.")
        return "\n".join(lines) + f"\n\n{latest.content}"
    count = len(stored.items)
    lines.append(
        f"Stored by its page: {count} key{'' if count == 1 else 's'}, {stored.size} bytes,"
        " shown after the content."
    )
    return "\n".join(lines) + f"\n\n{latest.content}\n\n{_stored_json(stored.items)}"


def _stored_json(items: dict[str, str]) -> str:
    """The items as one JSON object, cut before the first that would pass the limit."""
    pairs: list[str] = []
    length = 2
    for key, value in items.items():
        pair = f"{json.dumps(key)}: {json.dumps(value)}"
        if length + len(pair) + 2 * bool(pairs) > _STORED_SHOWN:
            break
        length += len(pair) + 2 * bool(pairs)
        pairs.append(pair)
    text = "What the page stored, as JSON:\n{" + ", ".join(pairs) + "}"
    left = len(items) - len(pairs)
    if left:
        text += f"\n... and {left} more key{'' if left == 1 else 's'}"
    return text


def _parsed[T: BaseModel](model: type[T], args: dict[str, JsonValue]) -> T:
    try:
        return model.model_validate(args)
    except ValidationError as error:
        raise ToolRefusedError(problems(error)) from error


async def _refusing[T](work: Awaitable[T]) -> T:
    try:
        return await work
    except NestError as error:
        raise ToolRefusedError(str(error)) from error
