from harness.errors import HarnessError


class AppNotInstalledError(HarnessError):
    status_code = 424


class LocalAppError(HarnessError):
    """`open` failed for another reason."""

    status_code = 502
