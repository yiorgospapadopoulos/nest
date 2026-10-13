from typing import Literal

from pydantic import BaseModel, ConfigDict

from harness.sessions.models import Text

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
    # An untracked folder that is a git repository of its own (`lib/`): harness does not
    # commit it (BUG-65).
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


class ReviewCommit(BaseModel):
    sha: str
    subject: str


class SessionDiff(BaseModel):
    # The commit the work is compared with; None when the repository had no commits.
    base: str | None
    head: ReviewHead
    # Commits on HEAD that neither the base nor the work harness published holds: made
    # behind the review's back, they are published with the work (SEC-02), newest first.
    commits: list[ReviewCommit]
    files: list[FileDiff]
    stats: DiffStats


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
    # Publish even though the agent changed git refs itself (D013 layer 4).
    acknowledge_violation: bool = False
    # HEAD's commit as the review showed it; approving is refused if HEAD moved since.
    expected_head: str | None = None
    # Push to origin's current URL and remember it, after the user saw that it is not the
    # URL harness recorded (D050); it must match origin's push URL exactly.
    confirm_remote_url: str | None = None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Text
