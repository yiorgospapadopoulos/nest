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
