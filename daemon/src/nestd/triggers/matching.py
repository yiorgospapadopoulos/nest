"""Whether a GitHub event passes a trigger's filters (B148)."""

from fnmatch import fnmatchcase

from nestd.triggers.models import EventFilter, GitHubEvent


def first_match(rule: EventFilter, event: GitHubEvent, me: str | None) -> bool:
    """The checks that need nothing more than the feed: the kind and the author. A pull
    request that passes them is read before `matches`, for its labels and branch.
    """
    return event.kind in rule.events and _author_counts(rule, event, me)


def matches(rule: EventFilter, event: GitHubEvent, me: str | None) -> bool:
    """`me` is the user's GitHub login, when known."""
    if not first_match(rule, event, me):
        return False
    if rule.labels and event.labels is not None:
        wanted = {label.lower() for label in rule.labels}
        if not any(label.lower() in wanted for label in event.labels):
            return False
    return not (
        rule.branches
        and event.branch is not None
        and not any(fnmatchcase(event.branch, pattern) for pattern in rule.branches)
    )


def _author_counts(rule: EventFilter, event: GitHubEvent, me: str | None) -> bool:
    if rule.authors == "everyone":
        return True
    if event.bot:
        return False
    if rule.authors == "others" and me is not None:
        return event.author.lower() != me.lower()
    return True
