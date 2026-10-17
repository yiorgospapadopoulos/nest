"""The artifact tools every chat and pixie run gets (B79). A run's tools act for its chat:
what a subagent saves belongs to the chat too.
"""

from collections.abc import Awaitable

from pydantic import BaseModel, JsonValue, ValidationError

from nestd.artifacts.models import CONTENT_MAX, KINDS, TITLE_MAX, ArtifactKind, Origin
from nestd.artifacts.service import Artifacts
from nestd.errors import NestError
from nestd.pixies.habit_models import problems
from nestd.providers.base import AgentTool, ToolRefusedError
from nestd.sessions.models import Session

CREATE_ARTIFACT = "create_artifact"
UPDATE_ARTIFACT = "update_artifact"

# What a page may do: the clients' page policy (D110) allows these hosts and nothing else.
_RULES = (
    "Markdown supports tables, Mermaid diagrams (```mermaid blocks) and code blocks. An HTML"
    " page may load scripts only from cdnjs.cloudflare.com, cdn.jsdelivr.net/npm/, unpkg.com,"
    " cdn.tailwindcss.com and code.jquery.com, and stylesheets and fonts only from Google"
    " Fonts, each with an exact version (react@18.3.1, never react or react@18); everything"
    " else inline, images as data: URIs, and no fetch, forms, storage or navigation. For"
    " React, load React, ReactDOM and Babel standalone from these hosts with"
    ' <script type="text/babel">. Define colors as CSS variables with a prefers-color-scheme:'
    " dark block and an explicit body background (canvas charts (Chart.js) need real colors,"
    " read with getComputedStyle, not var() strings), fit phone width with no sideways scroll,"
    " and set a short <title>."
)

# For the system prompts of chats and pixies.
ARTIFACT_NOTE = (
    "To give the user a long report, summary, comparison or plan, save it as an artifact "
    "with create_artifact (Markdown, or an HTML page such as a chart, diagram or small app) "
    "instead of a long chat message or a file in the repository, then reply briefly; "
    f"update_artifact saves a new version of one you created. {_RULES}"
)

_CONTENT: dict[str, JsonValue] = {
    "type": "string",
    "description": f"The whole document, at most {CONTENT_MAX} bytes, shown sandboxed. {_RULES}",
}
_TITLE: dict[str, JsonValue] = {
    "type": "string",
    "description": f"A short title, at most {TITLE_MAX} characters.",
}


class _Create(BaseModel):
    title: str
    kind: ArtifactKind
    content: str


class _Update(BaseModel):
    artifact_id: str
    content: str
    title: str | None = None


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
            artifacts.create(origin, request.kind, request.title, request.content)
        )
        return (
            f"Saved artifact {artifact.id} (version 1): {artifact.title}. The user opens it"
            " from the card in this chat; to change it, call update_artifact with this id."
        )

    async def update(args: dict[str, JsonValue]) -> str:
        request = _parsed(_Update, args)
        artifact = await _refusing(
            artifacts.update(origin, request.artifact_id, request.content, request.title)
        )
        return (
            f"Saved version {artifact.latest_version} of artifact {artifact.id}: {artifact.title}."
        )

    return (
        AgentTool(
            CREATE_ARTIFACT,
            "Save a Markdown document or an HTML page as an artifact the user opens in Nest's"
            " reader, such as a report, summary, comparison, plan, chart or diagram. Returns its"
            " id.",
            {
                "type": "object",
                "properties": {
                    "title": _TITLE,
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "content": _CONTENT,
                },
                "required": ["title", "kind", "content"],
            },
            create,
        ),
        AgentTool(
            UPDATE_ARTIFACT,
            "Save a new version of an artifact this chat created; earlier versions are kept.",
            {
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "content": _CONTENT,
                    "title": {**_TITLE, "description": "A new title; left out keeps the title."},
                },
                "required": ["artifact_id", "content"],
            },
            update,
        ),
    )


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
