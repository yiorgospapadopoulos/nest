"""What approve checks in the checkout before it commits: git-lfs (PL-17) and index flags
that would commit other content than the review shows (SEC-10).
"""

import asyncio
from collections.abc import Collection
from pathlib import Path

from nestd.gitops.hardened import run_hardened_git

ATTRIBUTES = ".gitattributes"
_LFS = "filter=lfs"


async def uses_lfs(cwd: Path) -> bool:
    """Whether an attributes file of the repository names the git-lfs filter: a
    `.gitattributes` anywhere in the work, tracked or not, or `info/attributes`.
    """
    listing = await run_hardened_git(
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd
    )
    files = [
        cwd / path
        for path in listing.split("\0")
        if path == ATTRIBUTES or path.endswith(f"/{ATTRIBUTES}")
    ]
    info = await run_hardened_git(["rev-parse", "--git-path", "info/attributes"], cwd)
    files.append(cwd / info.strip())
    return await asyncio.to_thread(_names_lfs, files)


def _names_lfs(files: list[Path]) -> bool:
    for file in files:
        if not file.is_file():
            continue
        for line in file.read_text(errors="replace").splitlines():
            if not line.lstrip().startswith("#") and _LFS in line.split():
                return True
    return False


async def index_flagged(cwd: Path, paths: Collection[str]) -> list[str]:
    """The paths among `paths` whose index entry is marked assume-unchanged or
    skip-worktree: git then keeps showing the staged file, while `git commit -- <file>`
    takes the working one.
    """
    listing = await run_hardened_git(["ls-files", "-v", "-z"], cwd)
    flagged: list[str] = []
    for entry in filter(None, listing.split("\0")):
        tag, path = entry[0], entry[2:]
        # `ls-files -v` tags an assume-unchanged entry in lower case, skip-worktree `S`.
        if path in paths and (tag.islower() or tag == "S"):
            flagged.append(path)
    return sorted(flagged)
