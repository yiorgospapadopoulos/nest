from typing import Literal

from pydantic import BaseModel, ConfigDict

from nestd.sessions.models import Text

type FileStatus = Literal["added", "modified", "deleted", "renamed"]
type LineKind = Literal["context", "add", "delete"]


class DiffLine(BaseModel):
    kind: LineKind
    text: str
    old_line: int | None
    new_line: int | None


class Hunk(BaseModel):
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    # The text after the @@ range, usually the enclosing function.
    header: str
    lines: list[DiffLine]


class FileDiff(BaseModel):
    path: str
    # The previous path of a renamed file.
    old_path: str | None
    status: FileStatus
    additions: int
    deletions: int
    binary: bool
    # Lines beyond the per-file limit are left out; the counts still include them.
    truncated: bool
    hunks: list[Hunk]
    # A git repository of its own that Nest does not commit (BUG-65, SEC-14): an
    # untracked folder (`lib/`), or one staged as a gitlink (`lib`) that is neither in the
    # base nor declared in `.gitmodules`.
    nested_repository: bool = False


class DiffStats(BaseModel):
    files: int
    additions: int
    deletions: int


class ReviewHead(BaseModel):
    # None while the repository has no commits.
    commit: str | None
    # The branch HEAD names, such as `main`, where an approved push goes; None when detached.
    branch: str | None


class SessionDiff(BaseModel):
    # The commit the work is compared with, HEAD's (B58); None when the repository has no
    # commits.
    base: str | None
    head: ReviewHead
    files: list[FileDiff]
    stats: DiffStats
    # A sha256 (hex) of the head and every file's status, mode and content,
    # shown or not; approving needs it, so it publishes only what the user saw.
    fingerprint: str


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commit_message: Text
    # In-place sessions only, and required there: the files to commit, so the user's
    # unrelated changes in the checkout are never committed.
    files: list[str] | None = None
    push: bool = True
    # Worktree sessions only; needs push.
    open_pr: bool = True
    pr_title: Text | None = None
    # Defaults to the session title and the agent's last summary.
    pr_body: str | None = None
    # HEAD's commit as the review showed it; approving is refused if HEAD moved since.
    expected_head: str | None = None
    # The review's fingerprint; approving is refused when the work no longer matches it.
    expected_fingerprint: str
    # Push to origin's current URL and remember it, after the user saw that it is not the
    # URL Nest recorded (D050); it must match origin's push URL exactly.
    confirm_remote_url: str | None = None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Text
