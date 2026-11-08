"""A pull request's status on GitHub as Nest keeps it (D034)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type PrState = Literal["open", "merged", "closed"]
# A single check; skipped and neutral checks never block a merge.
type CheckState = Literal["pending", "success", "failure", "skipped"]
# All checks together; none when the pull request has no checks.
type ChecksState = Literal["pending", "success", "failure", "none"]
type MergeMethod = Literal["squash", "merge", "rebase"]


class PrCheck(BaseModel):
    name: str
    state: CheckState
    url: str | None


class PrChecks(BaseModel):
    state: ChecksState
    # Skipped checks count as passed.
    passed: int
    failed: int
    pending: int
    items: list[PrCheck]


class AutoMerge(BaseModel):
    """GitHub's own auto-merge, turned on for the pull request (B149)."""

    method: MergeMethod
    enabled_at: datetime | None = None


class PrStatus(BaseModel):
    number: int
    url: str
    title: str
    state: PrState
    checks: PrChecks
    # None while GitHub is still working it out.
    mergeable: bool | None
    # GitHub's mergeStateStatus in lower case, such as clean, blocked, behind or draft.
    merge_state: str | None
    # approved, changes_requested or review_required; None without required reviews.
    review_decision: str | None
    head_sha: str | None
    created_at: datetime | None
    # The branch the pull request merges into (B149); None for a status read before B149.
    base_branch: str | None = None
    # GitHub merges the pull request by itself once its required checks pass (B149).
    auto_merge: AutoMerge | None = None
    # When Nest last saw something change, and when it last asked GitHub.
    changed_at: datetime
    updated_at: datetime

    def same_as(self, other: "PrStatus") -> bool:
        """Equal apart from when Nest looked."""
        ignored = {"changed_at", "updated_at"}
        return self.model_dump(exclude=ignored) == other.model_dump(exclude=ignored)

    def ready_to_merge(self) -> bool:
        return (
            self.state == "open"
            and self.checks.state in ("success", "none")
            and self.mergeable is True
            and self.merge_state not in _BLOCKING_MERGE_STATES
        )

    def blocked(self) -> bool:
        """Known not to be mergeable; an unknown mergeable state is not a block."""
        return (
            self.state != "open"
            or self.checks.state in ("pending", "failure")
            or self.mergeable is False
            or self.merge_state in _BLOCKING_MERGE_STATES
        )

    def failing_checks(self) -> list[str]:
        return [item.name for item in self.checks.items if item.state == "failure"]


_BLOCKING_MERGE_STATES = frozenset({"blocked", "dirty", "draft"})


# A review thread on lines of a file, or a review's own text (B101).
type ReviewCommentKind = Literal["thread", "review"]


class ReviewComment(BaseModel):
    """Feedback a reviewer left on the pull request, as untrusted text from GitHub."""

    # A thread's id with its last comment's, so a new reply makes it new again; a review's
    # own id.
    id: str
    kind: ReviewCommentKind
    path: str | None = None
    # The line now, or for an outdated thread the line it was on.
    line: int | None = None
    outdated: bool = False
    author: str
    # A thread's comments by people, in order, each as `author: text`.
    body: str
    url: str
    created_at: datetime | None


class PrReview(BaseModel):
    """The review comments waiting on a pull request Nest opened (B101). Resolved threads
    are gone from `items`; those whose id is in `sent` went to the agent.
    """

    items: list[ReviewComment]
    sent: list[str]
    changes_requested: bool
    # New comments go to the agent as they arrive, instead of waiting in Needs you.
    auto_send: bool = False
    # The thread items Nest replied on after pushing the agent's work for them; a new
    # comment gives a thread a new id, so it gets a new reply after the next push.
    replied: list[str] = Field(default_factory=list[str])

    def pending(self) -> list[ReviewComment]:
        sent = set(self.sent)
        return [item for item in self.items if item.id not in sent]

    def blocks_merge(self) -> bool:
        """An unresolved thread, or a review's text not sent to the agent yet, keeps the
        merge approval away: one item per chat waits in Needs you.
        """
        return any(item.kind == "thread" for item in self.items) or any(
            item.kind == "review" for item in self.pending()
        )


class MergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: MergeMethod = "squash"
    # Deletes the branch on GitHub; only when the user ticks it at the merge (B96).
    delete_branch: bool = False


class AutoMergeRequest(BaseModel):
    """Merge the pull request once its checks pass, or stop waiting (B149)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    method: MergeMethod = "squash"
    delete_branch: bool = False


class Restack(BaseModel):
    """A stacked chat's branch to move onto a new base after the branch under it changed
    (B149): its own commits are those after `upstream`.
    """

    upstream: str
    # The commit to rebase onto: a local branch, or for the default branch after a fetch,
    # origin's copy of it.
    onto: str
    # A branch of origin to fetch first; None when `onto` is local.
    fetch: str | None = None
    # The pull request's base once the branch is pushed.
    base: str
    # The new head after Nest rebased the branch on the Mac, waiting for the push.
    rebased: str | None = None
    # Why the rebase did not happen by itself, shown with the click that does it.
    error: str | None = None


class Stack(BaseModel):
    """A chat whose branch starts from another chat's branch (B149). Its pull request merges
    into that branch while the other one's pull request is open.
    """

    # The chat under this one; None once its work reached the default branch.
    parent: str | None
    # The branch the pull request merges into, while `parent` is set.
    parent_branch: str | None
    restack: Restack | None = None


type GuideState = Literal["writing", "ready", "failed"]


class PrGuide(BaseModel):
    """A review guide an agent wrote for the pull request, saved as an artifact (B149)."""

    state: GuideState
    # The pull request's head commit the guide was written for.
    head_sha: str | None = None
    artifact_id: str | None = None
    error: str | None = None
    # The comment on the pull request, once the user posted the guide there.
    comment_url: str | None = None
    written_at: datetime | None = None


class PrListItem(BaseModel):
    """A pull request Nest opened, for dashboards."""

    session_id: str
    repo: str
    session_title: str
    session_state: str
    url: str
    # Up to three lines; None for pull requests opened before summaries existed.
    summary: str | None
    # None until Nest first read it from GitHub.
    pr: PrStatus | None
