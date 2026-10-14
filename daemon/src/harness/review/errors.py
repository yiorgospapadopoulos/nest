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
    """The agent changed git refs itself, or HEAD holds commits the review never showed;
    publishing needs the user's acknowledgement (D013 layer 4, SEC-02).
    """

    code = "git_violation"

    def __init__(self) -> None:
        super().__init__(
            "The agent, or another program, changed git branches or commits outside "
            "harness. Check what changed, then confirm that you want to publish anyway."
        )

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class HeadChangedError(ConflictError):
    """HEAD is not the commit the review showed (SEC-02)."""

    code = "head_changed"

    def __init__(self) -> None:
        super().__init__(
            "The checkout moved to another commit after this review was made. Look at the "
            "review again before you publish."
        )

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class HiddenHistoryError(ConflictError):
    """Grafts or a shallow boundary make git skip commits a push would publish, so the
    review cannot list them (SEC-13).
    """

    code = "hidden_history"

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class ReviewChangedError(ConflictError):
    """The work, HEAD or its commits differ from the review the user approved."""

    code = "review_changed"

    def __init__(self) -> None:
        super().__init__(
            "The changes are different from the review you saw. Open the review again."
        )

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class LfsUnsupportedError(ConflictError):
    """git-lfs uploads its files from a pre-push hook, and harness runs no hooks (PL-17)."""

    code = "lfs_unsupported"

    def __init__(self) -> None:
        super().__init__(
            "This repository stores files with git-lfs, which harness cannot publish: it runs "
            "no git hooks, so git-lfs would not upload those files. Publish this work from "
            "Terminal."
        )

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class IndexFlagsError(ConflictError):
    """git is told to ignore changes to files the commit would take, so it could commit
    content other than the review showed (SEC-10).
    """

    code = "index_flags"

    def __init__(self, paths: list[str]) -> None:
        super().__init__(
            f"git is set to ignore changes to {', '.join(paths)} in this checkout "
            "(assume-unchanged or skip-worktree), so harness could commit something other "
            "than the review shows. Clear that in Terminal with git update-index "
            "--no-assume-unchanged <file> and git update-index --no-skip-worktree <file>, "
            "then open the review again."
        )
        self.paths = paths

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code, "paths": list(self.paths)}


class BackgroundRunningError(ConflictError):
    """The agent's background tasks could change the tree while it is committed (BUG-57)."""

    code = "background_running"

    def __init__(self) -> None:
        super().__init__(
            "The agent still has background tasks running, and they could change files while "
            "harness commits. Wait until they finish, or stop the agent, then approve again."
        )

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class NestedRepositoryError(ConflictError):
    """`git add` would commit a repository inside the work as a submodule that points
    nowhere (BUG-65).
    """

    code = "nested_repository"

    def __init__(self, paths: list[str]) -> None:
        super().__init__(
            "harness does not commit a git repository inside the work, and found "
            f"{', '.join(paths)}. Delete it or add it to .gitignore, then approve again."
        )
        self.paths = paths

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code, "paths": list(self.paths)}


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
    """The checkout is on something a push could read as an option, not a plain branch, or
    a worktree is not on its session's branch (SEC-06).
    """

    code = "unsafe_branch"

    def __init__(self, branch: str, worktree_branch: str | None = None) -> None:
        if worktree_branch is None:
            message = (
                f"harness will not push {branch!r}: it is not a plain branch name and could "
                "be read as a push option; switch to a normal branch, or publish by hand"
            )
        else:
            message = (
                f"The chat's worktree is on {branch!r}, not on its own branch "
                f"{worktree_branch!r}, the only one harness pushes it to. Switch it back, or "
                "publish by hand."
            )
        super().__init__(message)
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
            f"origin pushes to {current}, which you have not confirmed. Confirm that address "
            "to push there."
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
            f"origin now pushes to {current} instead of {confirmed_url}, the address harness "
            "recorded. Check the repository's remotes, or confirm the new address to push "
            "there."
        )
