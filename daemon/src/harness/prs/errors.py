from harness.errors import ConflictError, HarnessError
from harness.gitops.runner import CommandError


class PrReadError(HarnessError):
    """gh could not read the pull request, or returned something unexpected."""

    status_code = 502

    def __init__(self, url: str, error: Exception) -> None:
        detail = error.stderr.strip() if isinstance(error, CommandError) else str(error)
        super().__init__(f"could not read pull request {url}: {detail}")


class NoPullRequestError(ConflictError):
    pass
