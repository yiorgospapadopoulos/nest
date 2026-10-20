"""The configuration page's errors and their HTTP status codes (B97)."""

from pydantic import JsonValue

from nestd.errors import ConflictError, NestError, NotFoundError


class PathNotAllowedError(NestError):
    """A path outside the allow-list: Nest neither reads nor writes it."""

    status_code = 403


class UnknownItemError(NotFoundError):
    pass


class ChangedOnDiskError(ConflictError):
    """The file changed since the client read it; it gets the version on disk."""

    def __init__(self, detail: str, current_version: str | None) -> None:
        super().__init__(detail)
        self.current_version = current_version

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "current_version": self.current_version}


class CodexSetupError(NestError):
    """Codex could not be asked or refused a change; only the kind of failure is named."""

    status_code = 502


class ConfigurationUnavailableError(NotFoundError):
    """Nest was started without Claude's or Codex's folder (tests only)."""
