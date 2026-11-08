"""Whether a GitHub user has write access to a repository (B148, D179): only their events
start runs by default, so a stranger's issue on a public repository starts nothing.

Asked with the user's `gh` as GitHub's collaborator permission, and remembered for a while.
When GitHub cannot be asked, the answer is unknown and nothing is remembered.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

from nestd.clock import Clock
from nestd.gitops.runner import CommandError, CommandRunner

logger = logging.getLogger(__name__)

KEEP = timedelta(minutes=10)
WRITE = frozenset({"admin", "maintain", "write"})


class WriteAccess:
    def __init__(self, run: CommandRunner, cwd: Path, clock: Clock) -> None:
        """`cwd` is a folder outside any repository, so gh reads nothing an agent wrote."""
        self._run = run
        self._cwd = cwd
        self._clock = clock
        self._known: dict[tuple[str, str], tuple[datetime, bool]] = {}

    async def has_write(self, repo: str, login: str) -> bool | None:
        """`repo` is `owner/name`; None when GitHub could not be asked."""
        if not login or "/" in login:
            return False
        key = (repo.lower(), login.lower())
        now = self._clock.now()
        known = self._known.get(key)
        if known is not None and now - known[0] < KEEP:
            return known[1]
        try:
            output = await self._run(
                [
                    *("gh", "api", f"repos/{repo}/collaborators/{login}/permission"),
                    *("--jq", ".permission"),
                ],
                self._cwd,
            )
            allowed = output.strip() in WRITE
        except (CommandError, OSError) as error:
            # An unknown user (404) or a repository whose collaborators the user may not
            # see (403) is a firm no; a rate limit or a network failure is not an answer.
            refused = isinstance(error, CommandError) and (
                "HTTP 404" in error.stderr
                or ("HTTP 403" in error.stderr and "rate limit" not in error.stderr)
            )
            if refused:
                allowed = False
            else:
                logger.warning("could not read a GitHub permission (%s)", type(error).__name__)
                return None
        self._known[key] = (now, allowed)
        return allowed
