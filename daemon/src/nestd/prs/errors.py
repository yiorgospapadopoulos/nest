from pydantic import JsonValue

from nestd.errors import ConflictError, NestError
from nestd.gitops.runner import CommandError


class PrReadError(NestError):
    """gh could not read the pull request, or returned something unexpected."""

    status_code = 502

    def __init__(self, url: str, error: Exception) -> None:
        detail = error.stderr.strip() if isinstance(error, CommandError) else str(error)
        super().__init__(f"could not read pull request {url}: {detail}")


class NoPullRequestError(ConflictError):
    pass


class NoFailingChecksError(ConflictError):
    """Nothing to send to the agent: no check of the pull request fails now (IMP-08)."""

    code = "no_failing_checks"

    def __init__(self) -> None:
        super().__init__("No checks of this pull request are failing now.")

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class NoReviewCommentsError(ConflictError):
    """Nothing to send to the agent: no review comment waits (B101)."""

    code = "no_review_comments"

    def __init__(self) -> None:
        super().__init__("No review comments of this pull request wait to be sent.")

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}
