"""Domain errors that the API maps to HTTP status codes."""

from pydantic import JsonValue


class NestError(Exception):
    status_code = 500

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self)}

    def headers(self) -> dict[str, str] | None:
        return None


class NotFoundError(NestError):
    status_code = 404


class ConflictError(NestError):
    status_code = 409


class InvalidInputError(NestError):
    status_code = 422
