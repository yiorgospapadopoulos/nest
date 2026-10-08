from pydantic import JsonValue

from harness.errors import ConflictError, HarnessError
from harness.gitops.remotes import scrub_credentials


class GitActionError(HarnessError):
    """A git or gh command of the approve flow failed; the review stays pending. Its
    output reaches clients without the credentials a remote URL may carry (H-06).
    """

    status_code = 502

    def __init__(self, step: str, stderr: str) -> None:
        stderr = scrub_credentials(stderr)
        super().__init__(f"git {step} failed: {stderr.strip()}")
        self.step = step
        self.stderr = stderr

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "step": self.step, "stderr": self.stderr}


class NothingToCommitError(ConflictError):
    pass


class GitViolationError(ConflictError):
    pass


class UnsafeRepoConfigError(ConflictError):
    """The repository's own config would run a program or send data elsewhere (D050)."""

    code = "unsafe_repo_config"

    def __init__(self, settings: list[str]) -> None:
        super().__init__(
            "harness will not publish while the repository's git config sets "
            f"{', '.join(settings)}; check and remove them (git config --unset <key>), "
            "or publish by hand"
        )
        self.settings = settings

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code, "settings": list(self.settings)}


class UnsafeBranchError(ConflictError):
    """The checkout is on something a push could read as an option, not a plain branch."""

    code = "unsafe_branch"

    def __init__(self, branch: str) -> None:
        super().__init__(
            f"harness will not push {branch!r}: it is not a plain branch name and could be "
            "read as a push option; switch to a normal branch, or publish by hand"
        )
        self.branch = branch

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code, "branch": self.branch}


class RemoteNotConfirmedError(ConflictError):
    """No push URL was recorded or confirmed for the repository (D050)."""

    code = "remote_not_confirmed"

    def __init__(self, remote_urls: list[str], confirmed_url: str | None = None) -> None:
        super().__init__(self._message(remote_urls, confirmed_url))
        self.remote_urls = remote_urls
        self.confirmed_url = confirmed_url

    def _message(self, remote_urls: list[str], confirmed_url: str | None) -> str:
        current = ", ".join(remote_urls) or "nothing"
        return (
            f"origin pushes to {current}, which you have not confirmed; "
            "approve again with confirm_remote_url to push there"
        )

    def payload(self) -> dict[str, JsonValue]:
        return {
            "detail": str(self),
            "code": self.code,
            "remote_urls": list(self.remote_urls),
            "confirmed_url": self.confirmed_url,
        }


class RemoteChangedError(RemoteNotConfirmedError):
    """origin no longer pushes to the confirmed URL only (D050)."""

    code = "remote_changed"

    def _message(self, remote_urls: list[str], confirmed_url: str | None) -> str:
        current = ", ".join(remote_urls) or "nothing"
        return (
            f"origin now pushes to {current} instead of {confirmed_url}, the URL harness "
            "recorded; check the repository's remotes, or approve again with "
            "confirm_remote_url to push there"
        )
