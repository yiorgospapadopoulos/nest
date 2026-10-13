"""Pixie errors the API maps to status codes."""

from harness.errors import ConflictError, InvalidInputError, NotFoundError


class PixieNotFoundError(NotFoundError):
    pass


class DuplicateSlugError(ConflictError):
    pass


class InvalidSlugError(InvalidInputError):
    pass


class InvalidFileNameError(InvalidInputError):
    pass
