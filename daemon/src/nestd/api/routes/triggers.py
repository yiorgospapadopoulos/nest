"""A project's GitHub triggers (B148): each matching event starts a chat in the project."""

from fastapi import APIRouter, Response, status

from nestd.api.deps import Context, RequireDevice
from nestd.triggers.models import ChatTrigger, NewChatTrigger, TriggerActivity, UpdateChatTrigger

router = APIRouter(prefix="/api/repos", dependencies=[RequireDevice])


@router.get("/{name}/triggers")
async def list_triggers(name: str, ctx: Context) -> list[ChatTrigger]:
    return ctx.chat_triggers.of_repo(name)


@router.get("/{name}/triggers/activity")
async def trigger_activity(name: str, ctx: Context) -> list[TriggerActivity]:
    """What each trigger did last; later ones come as `trigger.activity`."""
    return await ctx.chat_triggers.activity(name)


@router.post("/{name}/triggers", status_code=status.HTTP_201_CREATED)
async def create_trigger(name: str, body: NewChatTrigger, ctx: Context) -> ChatTrigger:
    """422 for a plain folder or a project without a GitHub remote. Announced with the
    project as `repo.updated`.
    """
    return await ctx.chat_triggers.create(name, body)


@router.patch("/{name}/triggers/{trigger_id}")
async def update_trigger(
    name: str, trigger_id: str, body: UpdateChatTrigger, ctx: Context
) -> ChatTrigger:
    return await ctx.chat_triggers.update(name, trigger_id, body)


@router.delete("/{name}/triggers/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trigger(name: str, trigger_id: str, ctx: Context) -> Response:
    await ctx.chat_triggers.delete(name, trigger_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
