"""What the local model API serves (B106), and how a chat names a local model."""

from typing import Annotated, Literal, TypeGuard

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# A chat's model `local:<id>` runs that local model.
LOCAL_PREFIX = "local:"

type ToolsRating = Literal["good", "weak", "none", "unknown"]
# The apps Nest can start: LM Studio's server and Ollama.
type StartApp = Literal["lmstudio", "ollama"]
# The engine local chats run on.
type LocalEngine = Literal["claude", "codex"]


def is_local(model: str | None) -> TypeGuard[str]:
    return model is not None and model.startswith(LOCAL_PREFIX)


def local_id(model: str) -> str:
    """The local model's id in a `local:` model."""
    return model.removeprefix(LOCAL_PREFIX)


def local_ref(model_id: str) -> str:
    return LOCAL_PREFIX + model_id


class LocalModel(BaseModel):
    id: str
    server_id: str
    # The server's own id for it.
    model: str
    name: str
    address: str
    app: str | None
    context: int | None
    tools: ToolsRating
    weak_reason: str | None
    vision: bool
    thinking: bool
    # Whether its server answers now.
    running: bool
    has_key: bool
    # When it takes much of this Mac's memory, one sentence saying so.
    memory_warning: str | None = None


class LocalModelList(BaseModel):
    models: list[LocalModel]
    engine: LocalEngine
    local_only: bool


class FoundModel(BaseModel):
    """A model a server serves, as found or checked; `added` when Nest has it already."""

    address: str
    app: str | None
    model: str
    name: str
    context: int | None
    tools: ToolsRating
    weak_reason: str | None
    vision: bool
    thinking: bool
    added: bool
    # When it takes much of this Mac's memory, one sentence saying so.
    memory_warning: str | None = None


class DownloadedModel(BaseModel):
    """A model on disk that no running server serves."""

    name: str
    # Where it was found, such as "LM Studio" or "Hugging Face".
    source: str
    path: str
    # What to do to use it, in one sentence.
    hint: str
    # The app Nest can start to serve it.
    start: StartApp | None


class FoundModels(BaseModel):
    running: list[FoundModel]
    downloaded: list[DownloadedModel]


class LocalServerInfo(BaseModel):
    address: str
    app: str | None
    # Which APIs it answers: Anthropic Messages, OpenAI Responses, Chat Completions.
    messages: bool
    responses: bool
    chat: bool


type CheckError = Literal["unreachable", "no_tools", "no_models"]


class CheckResult(BaseModel):
    ok: bool
    error: CheckError | None
    server: LocalServerInfo | None
    models: list[FoundModel]


class LocalModelUsage(BaseModel):
    id: str
    input_tokens: int
    output_tokens: int


class LocalUsage(BaseModel):
    """Today's tokens, by the local calendar."""

    today_tokens: int
    models: list[LocalModelUsage]


class SetupState(BaseModel):
    first_run: bool
    local_only: bool


type Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckServer(_Strict):
    address: Address
    key: str | None = None


class AddModels(_Strict):
    address: Address
    key: str | None = None
    models: list[str] = Field(min_length=1)


class SetEngine(_Strict):
    engine: LocalEngine


class StartServer(_Strict):
    app: StartApp
