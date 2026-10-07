"""Layer 4 of the agent git block (D013): compare refs before and after each turn.

Worktrees share refs with the main checkout, so a commit the user makes elsewhere in the
repo during a turn is reported too. Every change is reported; the user decides.
"""

from contextlib import suppress
from pathlib import Path

from pydantic import JsonValue

from harness.gitops.runner import GitError, run_git


async def snapshot_refs(cwd: Path) -> dict[str, str]:
    """Empty for a plain folder (D041): if the agent makes it a repository, the commits it
    makes there are new refs at the end of the turn.
    """
    try:
        output = await run_git(["for-each-ref", "--format=%(objectname) %(refname)"], cwd)
    except GitError as error:
        if error.not_a_repository:
            return {}
        raise
    refs = {ref: sha for sha, ref in (line.split(" ", 1) for line in output.splitlines())}
    with suppress(GitError):  # no commits yet
        refs["HEAD"] = (await run_git(["rev-parse", "--verify", "HEAD"], cwd)).strip()
    return refs


def changed_refs(before: dict[str, str], after: dict[str, str]) -> list[JsonValue]:
    return [
        {"ref": ref, "before": before.get(ref), "after": after.get(ref)}
        for ref in sorted(before.keys() | after.keys())
        if before.get(ref) != after.get(ref)
    ]
