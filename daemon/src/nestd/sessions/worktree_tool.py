"""The tool a chat's agent moves the chat between worktrees with, on every engine (B119)."""

from collections.abc import Awaitable
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from nestd.errors import NestError
from nestd.providers.base import AgentTool, ToolRefusedError
from nestd.sessions.models import Session
from nestd.sessions.moves import PROJECT, WorktreeMoves

WORKTREE_TOOL = "worktree"

# For the system prompt of chats that have the tool.
WORKTREE_NOTE = (
    "This chat can change where it works: when the user asks to remove a worktree, make a new "
    f"one or go back to one, use the {WORKTREE_TOOL} tool, and do not run git worktree add or "
    "remove, EnterWorktree or ExitWorktree yourself."
)

_DESCRIPTION = (
    "Change where this chat works, when the user asks you to in this chat: do it then, and do"
    " not do it on your own. The chat goes on with this conversation in the new place. Never"
    " run git worktree add or git worktree remove, EnterWorktree or ExitWorktree yourself:"
    " Nest then loses track of where the chat works.\n"
    "Actions: list shows the project's worktrees. remove deletes a worktree, the chat's"
    " current one unless `worktree` names another, even one a deleted chat left behind; its"
    " branch stays, and after removing the current one the chat works in the project folder."
    " new makes a worktree from branch `base` (the project's default branch when left out) on"
    " a new branch, named `branch` or chosen for you, and moves the chat to it; the earlier"
    " worktree stays. back moves the chat to an existing worktree named by `worktree`, or to"
    f" the project folder with {PROJECT!r}. cancel forgets what this turn recorded.\n"
    "Nest does what you ask and does not judge the work: before remove, check with git whether"
    " the worktree has uncommitted changes or commits that are not merged, and if something"
    " looks unmerged tell the user and ask before calling this. A squash merge leaves commits"
    " that look unmerged.\n"
    "Changes happen when this turn ends, not during it: finish your reply, and expect the"
    " folder to change only with the next message."
)

_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["list", "remove", "new", "back", "cancel"]},
        "worktree": {
            "type": "string",
            "description": "A worktree by folder name, path or branch.",
        },
        "base": {"type": "string", "description": "For new: the local branch to start from."},
        "branch": {"type": "string", "description": "For new: the new branch's name."},
    },
    "required": ["action"],
}


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["list", "remove", "new", "back", "cancel"]
    worktree: str | None = None
    base: str | None = None
    branch: str | None = None


def worktree_tool(moves: WorktreeMoves, session: Session) -> AgentTool:
    session_id = session.id

    async def handle(args: dict[str, JsonValue]) -> str:
        try:
            request = _Request.model_validate(args)
        except ValidationError as error:
            raise ToolRefusedError(str(error)) from error
        match request.action:
            case "list":
                return await _refusing(moves.listing(session_id))
            case "remove":
                return await _refusing(moves.remove(session_id, request.worktree))
            case "new":
                return await _refusing(moves.new(session_id, request.branch, request.base))
            case "back":
                if request.worktree is None:
                    msg = f"Name the worktree to go back to, or {PROJECT!r}."
                    raise ToolRefusedError(msg)
                return await _refusing(moves.back(session_id, request.worktree))
            case "cancel":
                return await _refusing(moves.cancel_recorded(session_id))

    return AgentTool(WORKTREE_TOOL, _DESCRIPTION, _SCHEMA, handle)


async def _refusing[T](work: Awaitable[T]) -> T:
    try:
        return await work
    except NestError as error:
        raise ToolRefusedError(str(error)) from error
