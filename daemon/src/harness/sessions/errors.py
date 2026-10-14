from pydantic import JsonValue

from harness.errors import ConflictError, NotFoundError


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


class DirtyCheckoutError(ConflictError):
    def __init__(self, files: list[str]) -> None:
        super().__init__("the checkout has uncommitted changes; set allow_dirty to proceed")
        self.files = files

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "files": list(self.files)}


class CannotRewindError(ConflictError):
    """The files cannot be restored to before the message (IMP-02)."""

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
