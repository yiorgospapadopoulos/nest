"""Whether a GitHub event passes a trigger's filters (B148). Whether its author has write
access, the default, is asked of GitHub separately (`WriteAccess`).
"""

from fnmatch import fnmatchcase

from nestd.triggers.models import EventFilter, GitHubEvent


def first_match(rule: EventFilter, event: GitHubEvent) -> bool:
    """The checks that need nothing more than the feed: the kind, and no bots unless
    everyone counts. A pull request that passes them is read before `matches`, for its
    labels and branch.
    """
    return event.kind in rule.events and (rule.authors == "everyone" or not event.bot)


def matches(rule: EventFilter, event: GitHubEvent) -> bool:
    if not first_match(rule, event):
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
