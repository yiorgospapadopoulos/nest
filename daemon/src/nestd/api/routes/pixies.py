"""Pixies: saved agents with a soul, memory and their own chat (D072)."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from nestd.api.deps import Context, RequireDevice
from nestd.pixies.habit_models import CreateHabit, Habit, HabitRun, ReadReports, UpdateHabit
from nestd.pixies.models import (
    CreatePixie,
    FileText,
    Pixie,
    PixieActivity,
    PixieOrder,
    SearchHit,
    UpdatePixie,
    WriteFile,
)
from nestd.sessions.models import SendMessage, SendResult

router = APIRouter(prefix="/api/pixies", dependencies=[RequireDevice])


@router.get("")
async def list_pixies(ctx: Context) -> list[Pixie]:
    return await ctx.pixies.list_pixies()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_pixie(body: CreatePixie, ctx: Context) -> Pixie:
    """Fields left out start as `GET /api/pixie-settings` says (D104)."""
    return await ctx.pixies.create(body.with_defaults(ctx.settings.pixies))


@router.put("/order")
async def reorder_pixies(body: PixieOrder, ctx: Context) -> list[Pixie]:
    """Names every pixie once, in the new order (422 otherwise); returns them in it.
    Publishes `pixie.updated` for each pixie whose position changed.
    """
    return await ctx.pixies.reorder(body.ids)


@router.get("/{pixie_id}")
async def get_pixie(pixie_id: str, ctx: Context) -> Pixie:
    return await ctx.pixies.get(pixie_id)


@router.patch("/{pixie_id}")
async def update_pixie(pixie_id: str, body: UpdatePixie, ctx: Context) -> Pixie:
    """`"model": null` or `"effort": null` sets it back to the default; `"team_id": null`
    leaves the team (404 for an unknown team). 422 when the model does not run in the
    chosen mode; a pixie in Auto moved to a model without it asks again (`default`), as a
    chat does.
    """
    return await ctx.pixies.update(pixie_id, body)


@router.delete("/{pixie_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pixie(pixie_id: str, ctx: Context) -> Response:
    """Stops and deletes its chats and removes its soul, memory and notes."""
    await ctx.pixies.delete(pixie_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{pixie_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_pixie(pixie_id: str, ctx: Context) -> Pixie:
    """A copy right after the original, in its team: "<name> 2" with slug `<slug>-2` (the
    next free number), every setting, the soul, memory, notes and archive; no chat.
    """
    return await ctx.pixies.duplicate(pixie_id)


@router.post("/{pixie_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_to_pixie(pixie_id: str, body: SendMessage, ctx: Context) -> SendResult:
    """Starts the pixie's chat with this message, or sends it to the open one; while a turn
    runs the message is queued and comes back as `queued_message`."""
    return await ctx.pixies.send(pixie_id, body.text, body.attachment_ids)


@router.post("/{pixie_id}/reset")
async def reset_pixie(pixie_id: str, ctx: Context) -> Pixie:
    """Archives the chat; the next message starts a new one. Soul and memory stay."""
    return await ctx.pixies.reset(pixie_id)


@router.get("/{pixie_id}/files/{name:path}")
async def read_file(pixie_id: str, name: str, ctx: Context) -> FileText:
    """`soul`, `memory` or `notes/<name>`."""
    return await ctx.pixies.read_file(pixie_id, name)


@router.put("/{pixie_id}/files/{name:path}")
async def write_file(pixie_id: str, name: str, body: WriteFile, ctx: Context) -> FileText:
    """409 `stale_file` with the current text and hash when `hash` is not the current one."""
    return await ctx.pixies.write_file(pixie_id, name, body)


@router.get("/{pixie_id}/notes")
async def list_notes(pixie_id: str, ctx: Context) -> list[str]:
    return await ctx.pixies.notes(pixie_id)


@router.get("/{pixie_id}/search")
async def search_memory(
    pixie_id: str, ctx: Context, q: Annotated[str, Query(min_length=1, max_length=200)]
) -> list[SearchHit]:
    return await ctx.pixies.search(pixie_id, q)


@router.get("/{pixie_id}/activity")
async def pixie_activity(pixie_id: str, ctx: Context) -> list[PixieActivity]:
    """What the pixie did through its Nest tools, newest first; the latest 200 (B41)."""
    return await ctx.pixies.activity(pixie_id)


@router.get("/{pixie_id}/habits")
async def list_habits(pixie_id: str, ctx: Context) -> list[Habit]:
    """Oldest first, each with `next_due_at` and `last_run` (B42)."""
    return await ctx.habits.list_habits(pixie_id)


@router.post("/{pixie_id}/habits", status_code=status.HTTP_201_CREATED)
async def create_habit(pixie_id: str, body: CreateHabit, ctx: Context) -> Habit:
    """422 without a schedule or a trigger."""
    return await ctx.habits.create(pixie_id, body)


@router.patch("/{pixie_id}/habits/{habit_id}")
async def update_habit(pixie_id: str, habit_id: str, body: UpdateHabit, ctx: Context) -> Habit:
    """Fields left out are unchanged; `"schedule": null` removes the schedule (422 when no
    trigger is left). `"enabled": false` pauses it and true resumes it.
    """
    return await ctx.habits.update(pixie_id, habit_id, body)


@router.delete("/{pixie_id}/habits/{habit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_habit(pixie_id: str, habit_id: str, ctx: Context) -> Response:
    """Stops its run in progress and deletes it with its runs and their transcripts."""
    await ctx.habits.delete(pixie_id, habit_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{pixie_id}/habits/{habit_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_habit(pixie_id: str, habit_id: str, ctx: Context) -> HabitRun:
    """Run now: queues a run that starts once no other run is in progress, however late
    and whatever the usage, also while the habit is paused.
    """
    return await ctx.habits.run_now(pixie_id, habit_id)


@router.get("/{pixie_id}/habits/{habit_id}/runs")
async def habit_runs(pixie_id: str, habit_id: str, ctx: Context) -> list[HabitRun]:
    """Newest first: the latest 20 finished runs and any queued or running."""
    return await ctx.habits.runs(pixie_id, habit_id)


@router.post("/{pixie_id}/reports/read")
async def read_pixie_reports(pixie_id: str, ctx: Context) -> ReadReports:
    """Marks every unread report of the pixie read; returns their ids (B42)."""
    return await ctx.reports.mark_pixie_read(pixie_id)
