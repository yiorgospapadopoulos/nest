"""Layer 4 of the agent git block (D013): compare refs before and after each turn.

Worktrees share refs with the main checkout, so a commit the user makes elsewhere in the
repo during a turn is reported too. Every change is reported; the user decides.

Besides the refs, a snapshot records the branch HEAD names under `HEAD_BRANCH`, since a
push goes to that branch: switching it on the same commit is a change too (SEC-06).
"""

from contextlib import suppress
from pathlib import Path

from pydantic import JsonValue

from nestd.gitops.hardened import run_hardened_git
from nestd.gitops.runner import GitError

# Not a ref name (those have no spaces), so it never clashes with one.
HEAD_BRANCH = "HEAD branch"


async def snapshot_refs(cwd: Path) -> dict[str, str]:
    """Empty for a plain folder (D041): if the agent makes it a repository, the commits it
    makes there are new refs at the end of the turn.
    """
    try:
        output = await run_hardened_git(["for-each-ref", "--format=%(objectname) %(refname)"], cwd)
    except GitError as error:
        if error.not_a_repository:
            return {}
        raise
    refs = {ref: sha for sha, ref in (line.split(" ", 1) for line in output.splitlines())}
    with suppress(GitError):  # no commits yet
        refs["HEAD"] = (await run_hardened_git(["rev-parse", "--verify", "HEAD"], cwd)).strip()
    with suppress(GitError):  # a detached HEAD
        refs[HEAD_BRANCH] = (await run_hardened_git(["symbolic-ref", "-q", "HEAD"], cwd)).strip()
    return refs


async def with_own_changes(
    cwd: Path, baseline: dict[str, str] | None, remote: str
) -> dict[str, str]:
    """`baseline` updated with what the daemon's own commit and push change: HEAD, its
    branch and that branch's remote-tracking ref. Anything else that changed stays out, so
    the next audit still reports it. Without a baseline, the refs as they are now.
    """
    after = await snapshot_refs(cwd)
    if baseline is None:
        return after
    own = {"HEAD"}
    with suppress(GitError):  # a detached HEAD, or no repository
        branch = (await run_hardened_git(["symbolic-ref", "-q", "HEAD"], cwd)).strip()
        own |= {branch, f"refs/remotes/{remote}/{branch.removeprefix('refs/heads/')}"}
    refs = {ref: sha for ref, sha in baseline.items() if ref not in own}
    refs.update({ref: sha for ref, sha in after.items() if ref in own})
    return refs


def for_publish(baseline: dict[str, str], after: dict[str, str]) -> dict[str, str]:
    """`baseline` with what a publish uses as it is in `after`: HEAD's commit, the branch
    HEAD names and that branch (BUG-51). Other refs (other chats' branches, the user's own,
    remote-tracking refs, tags) keep their baseline values, so the next turn-end audit
    still reports a change to them.
    """
    used = {"HEAD", HEAD_BRANCH, after.get(HEAD_BRANCH)}
    refs = {ref: sha for ref, sha in baseline.items() if ref not in used}
    refs.update({ref: sha for ref, sha in after.items() if ref in used})
    return refs


def changed_refs(before: dict[str, str], after: dict[str, str]) -> list[JsonValue]:
    return [
        {"ref": ref, "before": before.get(ref), "after": after.get(ref)}
        for ref in sorted(before.keys() | after.keys())
        if before.get(ref) != after.get(ref)
    ]
