from pydantic import JsonValue

from harness.errors import ConflictError, HarnessError


class GitActionError(HarnessError):
    """A git or gh command of the approve flow failed; the review stays pending."""

    status_code = 502

    def __init__(self, step: str, stderr: str) -> None:
        super().__init__(f"git {step} failed: {stderr.strip()}")
        self.step = step
        self.stderr = stderr

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "step": self.step, "stderr": self.stderr}


class NothingToCommitError(ConflictError):
    pass


class GitViolationError(ConflictError):
    pass
