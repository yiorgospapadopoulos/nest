"""Git the daemon runs for itself in a repository an agent can write (I-009, D050).

Every command gets the `HARDENED` overrides. Commands that check out or compare file
contents (creating a worktree, `status`) also switch off the repository's own filter
drivers that could run a program, keeping git-lfs as it installs itself.
"""

from collections.abc import Sequence
from pathlib import Path

from nestd.gitops.runner import TIMEOUT_SECONDS, GitError, run_git
from nestd.gitops.safety import (
    GIT_CONFIG_LIST,
    HARDENED,
    filter_overrides,
    repo_settings,
)

GITLINK = "160000"
# What a fetch in the repository's config could otherwise start: bundles, submodules, a
# background gc.
_FETCH_OVERRIDES = (
    *("-c", "fetch.recurseSubmodules=false"),
    *("-c", "transfer.bundleURI=false"),
    *("-c", "gc.auto=0"),
    *("-c", "maintenance.auto=false"),
)
# Nothing may wait on a person. Not GIT_SSH_COMMAND: it would replace the user's own global
# `core.sshCommand`.
_FETCH_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "/usr/bin/false",
    "SSH_ASKPASS": "/usr/bin/false",
    "SSH_ASKPASS_REQUIRE": "force",
    "GIT_HTTP_LOW_SPEED_LIMIT": "1000",
    "GIT_HTTP_LOW_SPEED_TIME": "30",
}


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


async def remote_names(cwd: Path) -> list[str]:
    """The repository's configured remotes."""
    return (await run_hardened_git(["remote"], cwd)).splitlines()


async def run_fetch_git(remote: str, cwd: Path, time_limit: float) -> None:
    """Fetch `remote`'s branches into its own tracking refs and nothing else: the explicit
    refspec with `--refmap=` ignores any `remote.*.fetch` in the repository's config, so
    local branches, tags and the working tree stay as they are. Check `fetch_blockers`
    first, and that `remote` is safe inside a refspec.
    """
    args = [
        *HARDENED,
        *_FETCH_OVERRIDES,
        "fetch",
        "--quiet",
        "--no-tags",
        "--no-recurse-submodules",
        "--no-write-fetch-head",
        "--no-auto-maintenance",
        "--prune",
        "--no-prune-tags",
        "--refmap=",
        "--",
        remote,
        f"+refs/heads/*:refs/remotes/{remote}/*",
    ]
    await run_git(args, cwd, time_limit, env=_FETCH_ENV)
