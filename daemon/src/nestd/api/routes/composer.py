"""The composer's `!` shell commands and `#` memory for a chat (B59)."""

from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, StringConstraints

from nestd.api.deps import Context, RequireDevice
from nestd.composer.service import MemoryScope, MemoryWritten
from nestd.composer.shell import ShellResult

router = APIRouter(prefix="/api/sessions", dependencies=[RequireDevice])


class ShellCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)
    ]


class Remember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]
    scope: MemoryScope


@router.post("/{session_id}/shell")
async def run_shell(session_id: str, body: ShellCommand, ctx: Context) -> ShellResult:
    """Run a `!` command in the chat's folder. The client puts `context` before the text of
    the next message it sends. 409 `pixie_chat` in a pixie's chat or one a pixie started.
    """
    return await ctx.composer.run_shell(session_id, body.command)


@router.post("/{session_id}/memory")
async def remember(session_id: str, body: Remember, ctx: Context) -> MemoryWritten:
    """Add `- text` to the project's CLAUDE.md or the user's, creating it if missing."""
    return await ctx.composer.remember(session_id, body.text, body.scope)
