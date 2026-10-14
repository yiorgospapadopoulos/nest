"""Pixie errors the API maps to status codes."""

from pydantic import JsonValue

from harness.errors import ConflictError, InvalidInputError, NotFoundError


class PixieNotFoundError(NotFoundError):
    pass


class DuplicateSlugError(ConflictError):
    """The slug or handle is taken by a pixie or a team: they share one namespace."""


class TeamNotFoundError(NotFoundError):
    pass


class LeaderNotMemberError(ConflictError):
    """A team's leader must be one of its members."""

    code = "leader_not_member"

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class InvalidSlugError(InvalidInputError):
    pass


class InvalidFileNameError(InvalidInputError):
    pass


class InvalidOrderError(InvalidInputError):
    """A new order must name every pixie exactly once."""


class StaleFileError(ConflictError):
    """The file changed since the writer read it; carries the current text."""

    code = "stale_file"

    def __init__(self, name: str, text: str, current_hash: str) -> None:
        super().__init__(f"{name} changed since it was read")
        self.text = text
        self.current_hash = current_hash

    def payload(self) -> dict[str, JsonValue]:
        return {
            "detail": str(self),
            "code": self.code,
            "text": self.text,
            "hash": self.current_hash,
        }
