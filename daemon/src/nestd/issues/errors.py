from pydantic import ValidationError

from nestd.errors import ConflictError, InvalidInputError, NestError
from nestd.gitops.runner import CommandError
from nestd.prs.untrusted import one_line

MAX_REASON_CHARS = 200


class IssueReadError(NestError):
    """gh could not read the issues, or returned something unexpected."""

    status_code = 502

    def __init__(self, what: str, error: Exception) -> None:
        super().__init__(f"could not read {what}: {short_reason(error)}")


class IssueClosedError(ConflictError):
    def __init__(self, number: int) -> None:
        super().__init__(f"Issue #{number} is closed.")


class NoGitHubRemoteError(InvalidInputError):
    def __init__(self, repo: str) -> None:
        super().__init__(f"{repo} has no GitHub remote, so it has no issues to read")


def short_reason(error: Exception) -> str:
    """The last line gh printed, cleaned; the full output may quote anything."""
    if isinstance(error, CommandError):
        lines = error.stderr.strip().splitlines()
        return one_line(lines[-1])[:MAX_REASON_CHARS] if lines else "gh failed"
    if isinstance(error, ValidationError):
        return "gh answered something unexpected"
    return "gh is not available"
