from nestd.errors import NestError


class AppNotInstalledError(NestError):
    status_code = 424


class LocalAppError(NestError):
    """`open` failed for another reason."""

    status_code = 502
