"""Small session rules shared by the manager."""

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from pydantic import JsonValue

from nestd.attachments.store import Attachment
from nestd.providers.base import FileInput, ImageInput, UserInput
from nestd.sessions.errors import NoWorkspaceError, SessionClosedError
from nestd.sessions.models import Session, SessionState, UpdateSession
from nestd.worktrees.manager import Worktree


def session_changes(session: Session, request: UpdateSession, now: datetime) -> dict[str, object]:
    """The fields `request` actually changes, as session columns."""
    wanted: dict[str, object] = request.model_dump(exclude_none=True, exclude={"archived"})
    if request.archived is not None and request.archived != (session.archived_at is not None):
        wanted["archived_at"] = now if request.archived else None
    changes = {name: value for name, value in wanted.items() if getattr(session, name) != value}
    if request.permission_mode is not None and session.follows_claude_code_mode:
        # A chosen mode, even the placeholder's own, replaces Claude Code's (IMP-06).
        changes |= {"permission_mode": request.permission_mode, "follows_claude_code_mode": False}
    if request.title is not None and session.title_pending:
        # A name given by hand is never replaced by the engine's (B125).
        changes["title_pending"] = False
    return changes


def require_open(session: Session) -> None:
    if session.state is SessionState.CLOSED:
        msg = f"session {session.id!r} is closed"
        raise SessionClosedError(msg)


def require_cwd(session: Session) -> Path:
    if session.cwd is None:
        msg = f"session {session.id!r} has no working directory"
        raise NoWorkspaceError(msg)
    return session.cwd


def require_workspace(session: Session) -> Path:
    """The session's working directory, which must still exist on disk."""
    cwd = require_cwd(session)
    if not cwd.is_dir():
        msg = f"the working directory of session {session.id!r} no longer exists"
        raise NoWorkspaceError(msg)
    return cwd


def worktree_of(session: Session) -> Worktree | None:
    if session.worktree_path is None or session.branch is None:
        return None
    return Worktree(session.worktree_path, session.branch, session.base_ref or "")


def among(path: Path, paths: Iterable[Path]) -> bool:
    """Whether `path` is one of `paths`, once resolved; reads the disk."""
    target = path.resolve()
    return any(other.resolve() == target for other in paths)


def pr_finished(session: Session) -> bool:
    """A chat that goes on after its pull request was merged or closed may open another
    (B119); until then a chat has the one.
    """
    return session.movable and session.pr is not None and session.pr.state != "open"


def user_input(text: str, attachments: list[Attachment]) -> UserInput:
    """Images go to the agent as image content; other files by absolute path."""
    return UserInput(
        text=text,
        images=tuple(ImageInput(a.media_type, a.read_base64()) for a in attachments if a.is_image),
        files=tuple(FileInput(a.path, a.media_type) for a in attachments if not a.is_image),
    )


def attachment_summary(attachment: Attachment) -> JsonValue:
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "media_type": attachment.media_type,
        "size": attachment.size,
    }
