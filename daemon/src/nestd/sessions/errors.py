from pydantic import JsonValue

from nestd.errors import ConflictError, NotFoundError


class SessionNotFoundError(NotFoundError):
    pass


class SessionBusyError(ConflictError):
    pass


class SessionClosedError(ConflictError):
    pass


class NoTurnInProgressError(ConflictError):
    pass


class NoWorkspaceError(ConflictError):
    pass


class NoAgentRunError(ConflictError):
    """The session has no agent running, so nothing of it can be stopped (B59)."""


class TaskNotFoundError(NotFoundError):
    """The session's agent runs no task by that id (B59)."""


class CannotRewindError(ConflictError):
    """The files or the conversation cannot be restored to before the message, or a chat
    forked from it (IMP-02, B59).
    """

    code = "cannot_rewind"

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class PixieChatError(ConflictError):
    """What a pixie's chat does not allow: it goes with its pixie (reset or delete the
    pixie instead), and its files cannot be restored (D072).
    """

    code = "pixie_chat"

    def __init__(
        self, detail: str = "this is a pixie's chat; reset or delete the pixie instead"
    ) -> None:
        super().__init__(detail)

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class MessageTakenError(ConflictError):
    """The agent already read the queued message, so it can no longer be removed (B59)."""

    code = "message_taken"

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}
