"""The outside clients, their levels, and what the outside API takes and answers (B151).

The `nest` command and `nest mcp` read the same models, so both sides agree on the shape.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from nestd.config.models import Effort

type ClientKind = Literal["claude_code", "codex", "other", "shell"]
CLIENT_KINDS: tuple[ClientKind, ...] = ("claude_code", "codex", "other", "shell")
LABELS: dict[ClientKind, str] = {
    "claude_code": "Claude Code",
    "codex": "Codex",
    "other": "Other MCP apps",
    "shell": "nest command",
}


def client_kind(text: str) -> ClientKind | None:
    return next((kind for kind in CLIENT_KINDS if kind == text), None)


# Each level includes the ones before it.
type Access = Literal["read", "message", "full"]
ACCESS: tuple[Access, ...] = ("read", "message", "full")
ACCESS_LABELS: dict[Access, str] = {
    "read": "Read only",
    "message": "Read and message",
    "full": "Full",
}
# The name Nest's MCP server has in Claude Code's and Codex's config; Nest's own chats
# already have a server named "nest".
MCP_NAME = "nest-app"
# The modes a client may start a chat in: looser ones need the user in Nest (D180).
type StartMode = Literal["plan", "default", "acceptEdits"]
# As a pixie's defaults (D180).
MAX_RUNNING = 2
MAX_PER_DAY = 5
TEXT_MAX = 20_000

type Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class OutsideClient(BaseModel):
    """One client as Settings shows it."""

    kind: ClientKind
    label: str
    on: bool
    access: Access | None
    turned_on_at: datetime | None
    last_seen_at: datetime | None
    # What an app runs to reach Nest, `<nest> mcp --client <kind>`; for the `nest`
    # command, the command itself. None when the `nest` command is not installed.
    command: list[str] | None


class TurnOn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access: Access


class StartChat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: Text
    prompt: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TEXT_MAX)
    ]
    # None: Nest's default for the project.
    worktree: bool | None = None
    # The engine, such as "claude" or "codex"; None: the agent defaults' engine.
    engine: Text | None = None
    model: Text | None = None
    effort: Effort | None = None
    permission_mode: StartMode = "default"


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TEXT_MAX)
    ]


class Chat(BaseModel):
    id: str
    title: str
    project: str
    # Nest's state; `waiting_on` says what the user must answer in Nest.
    state: str
    status: str
    waiting_on: list[str]
    engine: str
    model: str | None
    permission_mode: str
    worktree: bool
    branch: str | None
    pr_url: str | None
    started_by: str
    created_at: datetime
    updated_at: datetime


class ChatDetails(Chat):
    # The agent's newest message of its own, whole.
    last_answer: str | None
    last_error: str | None


class Transcript(BaseModel):
    text: str
    # The entry number to read on from, when more follow.
    more: int | None


class Project(BaseModel):
    name: str
    path: str
    git: bool


class PixieEntry(BaseModel):
    # What to write after @ to call it.
    handle: str
    name: str
    kind: Literal["pixie", "team"]


class Status(BaseModel):
    version: str
    client: ClientKind
    access: Access
    running: int
    waiting: int


class TokenAnswer(BaseModel):
    """The socket's one-line answer."""

    token: str | None = None
    # "off": the client is switched off; "inside_nest": the asker runs inside Nest itself.
    error: Literal["off", "inside_nest", "unknown_client"] | None = None


class Refusal(BaseModel):
    detail: str
    # The level it needs, when the client's is too low.
    needs: Access | None = Field(default=None)
