"""Domain errors that the API maps to HTTP status codes."""

from pydantic import JsonValue


class HarnessError(Exception):
    status_code = 500

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self)}

    def headers(self) -> dict[str, str] | None:
        return None


class NotFoundError(HarnessError):
    status_code = 404


class ConflictError(HarnessError):
    status_code = 409


class InvalidInputError(HarnessError):
    status_code = 422
