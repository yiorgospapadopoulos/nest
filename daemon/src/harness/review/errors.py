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
