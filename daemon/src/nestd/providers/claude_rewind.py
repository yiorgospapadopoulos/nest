"""Restoring the files of a run to before a user message (IMP-02).

Claude Code keeps a checkpoint of the files the agent edits at each user message when the
run opens with file checkpointing. The SDK's `rewind_files` neither previews nor returns the
outcome, so the control request is sent through the SDK's query, which answers both.
"""

from typing import Any, cast

from nestd.providers.base import RewindResult

NOT_CONNECTED = "the agent is not connected"


async def rewind(client: object, checkpoint_id: str, dry_run: bool) -> RewindResult:
    """What restoring would change (`dry_run`), or what it changed; never raises."""
    query = getattr(client, "_query", None)
    if query is None:
        return RewindResult(can_rewind=False, error=NOT_CONNECTED)
    request = {"subtype": "rewind_files", "user_message_id": checkpoint_id, "dry_run": dry_run}
    try:
        response: object = await query._send_control_request(request)
    except Exception as error:
        # The engine refuses an impossible restore with an error, which the SDK raises.
        return RewindResult(can_rewind=False, error=str(error))
    return _result(cast("dict[str, Any]", response) if isinstance(response, dict) else {})


def _result(data: dict[str, Any]) -> RewindResult:
    files = data.get("filesChanged")
    entries = cast("list[object]", files) if isinstance(files, list) else []
    error = data.get("error")
    return RewindResult(
        can_rewind=data.get("canRewind") is True,
        files_changed=[entry for entry in entries if isinstance(entry, str)],
        insertions=_count(data.get("insertions")),
        deletions=_count(data.get("deletions")),
        error=error if isinstance(error, str) else None,
    )


def _count(value: object) -> int:
    return value if isinstance(value, int) else 0
