"""Git the daemon runs for itself in a repository an agent can write (I-009, D050).

Every command gets the `HARDENED` overrides. Commands that check out or compare file
contents (creating a worktree, `status`) also switch off the repository's own filter
drivers that could run a program, keeping git-lfs as it installs itself.
"""

from collections.abc import Sequence
from pathlib import Path

from harness.gitops.runner import TIMEOUT_SECONDS, GitError, run_git
from harness.gitops.safety import GIT_CONFIG_LIST, HARDENED, filter_overrides, repo_settings


async def run_hardened_git(
    args: Sequence[str], cwd: Path, time_limit: float = TIMEOUT_SECONDS
) -> str:
    """`git <HARDENED> <args>` in `cwd`; for commands that run no filter driver."""
    return await run_git([*HARDENED, *args], cwd, time_limit)


async def run_checkout_git(args: Sequence[str], cwd: Path) -> str:
    """Like `run_hardened_git`, with the repository's unsafe filter drivers switched off."""
    listing = GIT_CONFIG_LIST[1:]
    settings = repo_settings(await run_hardened_git(listing, cwd))
    try:
        overrides = filter_overrides(settings, only_unsafe=True)
    except ValueError as error:
        raise GitError(listing, None, str(error)) from None
    return await run_hardened_git([*overrides, *args], cwd)
