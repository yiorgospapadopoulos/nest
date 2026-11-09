"""Terminal agents use Nest (B151): the API outside clients reach with their own token,
and the Settings routes that switch them on and off.

Client tokens work only under `/api/outside`, and device tokens never do there, so a
client cannot reach the rest of Nest and a lost device token cannot pose as a client.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from starlette.requests import HTTPConnection

from nestd.api.deps import Context, RequireDevice
from nestd.outside.models import (
    Chat,
    ChatDetails,
    ClientKind,
    OutsideClient,
    PixieEntry,
    Project,
    SendMessage,
    StartChat,
    Status,
    Text,
    Transcript,
    TurnOn,
)
from nestd.outside.service import TRANSCRIPT_MAX
from nestd.outside.store import ClientRow


async def require_client(conn: HTTPConnection, ctx: Context) -> ClientRow:
    scheme, _, credentials = conn.headers.get("authorization", "").partition(" ")
    token = credentials.strip() if scheme.lower() == "bearer" else ""
    client = await ctx.outside.authenticate(token) if token else None
    if client is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return client


RequireClient = Depends(require_client)
Client = Annotated[ClientRow, RequireClient]
router = APIRouter(prefix="/api/outside", dependencies=[RequireClient])
settings_router = APIRouter(prefix="/api/outside-clients", dependencies=[RequireDevice])


class CallPixie(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: Text
    task: Text


@router.get("/status")
async def get_status(ctx: Context, client: Client) -> Status:
    return await ctx.outside.status(client)


@router.get("/projects")
async def list_projects(ctx: Context) -> list[Project]:
    return ctx.outside.projects()


@router.get("/chats")
async def list_chats(
    ctx: Context, project: str | None = None, state: str | None = None
) -> list[Chat]:
    return await ctx.outside.chats(project, state)


@router.get("/chats/{session_id}")
async def get_chat(session_id: str, ctx: Context) -> ChatDetails:
    return await ctx.outside.chat(session_id)


@router.get("/chats/{session_id}/transcript")
async def get_transcript(
    session_id: str,
    ctx: Context,
    since: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int | None, Query(ge=1, le=TRANSCRIPT_MAX)] = None,
) -> Transcript:
    return await ctx.outside.transcript(session_id, since, limit)


@router.post("/chats", status_code=status.HTTP_201_CREATED)
async def start_chat(body: StartChat, ctx: Context, client: Client) -> ChatDetails:
    return await ctx.outside.start(client, body)


@router.post("/chats/{session_id}/messages")
async def send_message(
    session_id: str, body: SendMessage, ctx: Context, client: Client
) -> ChatDetails:
    return await ctx.outside.send(client, session_id, body.text)


@router.get("/pixies")
async def list_pixies(ctx: Context) -> list[PixieEntry]:
    return await ctx.outside.pixies()


@router.post("/pixies/{handle}/call", status_code=status.HTTP_201_CREATED)
async def call_pixie(handle: str, body: CallPixie, ctx: Context, client: Client) -> ChatDetails:
    return await ctx.outside.call(client, body.project, handle, body.task)


@settings_router.get("")
async def list_clients(ctx: Context) -> list[OutsideClient]:
    return await ctx.outside.clients()


@settings_router.put("/{kind}")
async def turn_on(kind: ClientKind, body: TurnOn, ctx: Context) -> OutsideClient:
    return await ctx.outside.turn_on(kind, body.access)


@settings_router.delete("/{kind}")
async def turn_off(kind: ClientKind, ctx: Context) -> OutsideClient:
    return await ctx.outside.turn_off(kind)
