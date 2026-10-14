"""Git the daemon runs for itself in a repository an agent can write (I-009, D050).

Every command gets the `HARDENED` overrides. Commands that check out or compare file
contents (creating a worktree, `status`) also switch off the repository's own filter
drivers that could run a program, keeping git-lfs as it installs itself.
"""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from nestd.gitops.runner import TIMEOUT_SECONDS, CommandRunner, GitError, run_git
from nestd.gitops.safety import (
    GIT_CONFIG_LIST,
    HARDENED,
    RepoSetting,
    filter_overrides,
    repo_settings,
)

GITLINK = "160000"


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


async def nested_filter_overrides(cwd: Path, run: CommandRunner) -> list[str]:
    """`-c` options that switch off every filter driver named in the config of a populated
    submodule or nested repository under `cwd`, at any depth (SEC-08).

    `git add -A` runs `status` inside each of them, with their own config, which the agent
    can write; options given to the outer git reach those runs too.

    Raises GitError for a driver name `-c` cannot express.
    """
    settings: list[RepoSetting] = []
    seen = {await asyncio.to_thread(cwd.resolve)}
    pending = [cwd]
    while pending:
        root = pending.pop()
        index = await run(["git", *HARDENED, "ls-files", "-z", "--stage"], root)
        for entry in filter(None, index.split("\0")):
            info, _, path = entry.partition("\t")
            nested = root / path
            if not info.startswith(GITLINK) or not await asyncio.to_thread(_populated, nested):
                continue
            # A gitlink path can be a symlink to a folder already looked at.
            resolved = await asyncio.to_thread(nested.resolve)
            if resolved in seen:
                continue
            seen.add(resolved)
            listing = await run(["git", *HARDENED, *GIT_CONFIG_LIST[1:]], nested)
            settings += repo_settings(listing)
            pending.append(nested)
    try:
        return filter_overrides(settings)
    except ValueError as error:
        raise GitError(GIT_CONFIG_LIST[1:], None, str(error)) from None


def _populated(path: Path) -> bool:
    return (path / ".git").exists()
