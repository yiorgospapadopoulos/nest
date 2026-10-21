"""A git project's branch map (B96): its default branch, the branch its folder is on and
the branches checked out in linked worktrees, each hanging from the shown branch it
comes from.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from nestd.config.models import RepoConfig
from nestd.gitops.hardened import run_hardened_git
from nestd.repos.service import BRANCH_REF
from nestd.worktrees.manager import OWNED_WORKTREE_PREFIXES, claude_worktrees_dir

type Owner = Literal["nest", "claude", "other"]
# Among branches as far from the root, the branch of the project folder (or of no
# worktree) comes first, then other worktrees', then Nest's, which are seldom bases.
_KIND_ORDER: Mapping[Owner | None, int] = {None: 0, "claude": 1, "other": 1, "nest": 2}


class MapWorktree(BaseModel):
    path: Path
    # Nest's own (`nest-*`), Claude Code's (elsewhere in `.claude/worktrees/`) or other.
    owner: Owner


class MapBranch(BaseModel):
    name: str
    # Null for the root only.
    parent: str | None
    # The linked worktree the branch is checked out in.
    worktree: MapWorktree | None
    # The branch the project folder is on.
    here: bool


class BranchMap(BaseModel):
    default_branch: str | None
    # Null when the project folder is on a detached HEAD or a branch without commits.
    current_branch: str | None
    # Depth first from the root, siblings by name.
    branches: list[MapBranch]


@dataclass(frozen=True)
class Candidate:
    """A branch to place: its tip commit, its worktree, and the commit Nest started that
    worktree's chat from, when it did.
    """

    name: str
    tip: str
    worktree: MapWorktree | None = None
    base: str | None = None


def arrange(
    root: str, candidates: Sequence[Candidate], ahead: Mapping[tuple[str, str], int]
) -> list[tuple[str, str | None]]:
    """Each branch with its parent, depth first from `root`, siblings by name.

    `ahead[(b, c)]` counts the commits of `b` that `c` does not have (`c..b`). A branch's
    parent is the branch it has fewest commits beyond: its nearest fork point. Ties go to
    the root, then to the branch at the commit Nest started the worktree from, then to
    the one first in the order below.

    No cycles: a branch can only hang from the root or from a branch before it in the
    order of distance from the root, then kind (see `_KIND_ORDER`), then name. A worktree
    with nothing committed yet is as far from the root as the branch it came from, and
    still hangs from it.
    """

    def order(candidate: Candidate) -> tuple[int, int, str]:
        owner = None if candidate.worktree is None else candidate.worktree.owner
        return (ahead[(candidate.name, root)], _KIND_ORDER[owner], candidate.name)

    children: dict[str, list[str]] = {candidate.name: [] for candidate in candidates}
    for branch in candidates:
        if branch.name == root:
            continue
        eligible = [
            other
            for other in candidates
            if other.name == root or (other.name != branch.name and order(other) < order(branch))
        ]
        parent = min(
            eligible,
            key=lambda other: (
                ahead[(branch.name, other.name)],
                other.name != root,
                other.tip != branch.base,
                order(other),
            ),
        )
        children[parent.name].append(branch.name)
    placed: list[tuple[str, str | None]] = []
    pending: list[tuple[str, str | None]] = [(root, None)]
    while pending:
        name, parent = pending.pop()
        placed.append((name, parent))
        pending += [(child, name) for child in sorted(children[name], reverse=True)]
    return placed


@dataclass(frozen=True)
class Checkout:
    path: Path
    branch: str | None


async def read_branch_map(repo: RepoConfig, bases: Mapping[Path, str]) -> BranchMap:
    """The map of a git repo whose folder exists; `bases` maps the worktree paths of Nest's
    chats to the commits they started from.
    """
    main, *linked = await checkouts(repo.path)
    tips = await _tips(repo.path)
    current = main.branch if main.branch in tips else None
    shown: dict[str, Candidate] = {}
    for name in (repo.default_branch, current):
        if name is not None and name in tips:
            shown.setdefault(name, Candidate(name, tips[name]))
    for checkout in linked:
        if checkout.branch is None or checkout.branch not in tips or checkout.branch in shown:
            continue
        worktree = MapWorktree(path=checkout.path, owner=_owner(repo.path, checkout.path))
        shown[checkout.branch] = Candidate(
            checkout.branch, tips[checkout.branch], worktree, bases.get(checkout.path)
        )
    if not shown:
        return BranchMap(default_branch=repo.default_branch, current_branch=current, branches=[])
    default = repo.default_branch
    if default is not None and default in shown:
        root = default
    else:
        root = current if current is not None else min(shown)
    ahead = await _ahead(repo.path, list(shown.values()))
    return BranchMap(
        default_branch=repo.default_branch,
        current_branch=current,
        branches=[
            MapBranch(
                name=name,
                parent=parent,
                worktree=shown[name].worktree,
                here=name == current,
            )
            for name, parent in arrange(root, list(shown.values()), ahead)
        ],
    )


async def checkouts(path: Path) -> list[Checkout]:
    """The project folder first, then each linked worktree whose folder still exists."""
    output = await run_hardened_git(["worktree", "list", "--porcelain", "-z"], path)
    found: list[Checkout] = []
    for record in output.split("\0\0"):
        fields: dict[str, str] = {}
        for field in filter(None, record.split("\0")):
            key, _, value = field.partition(" ")
            fields[key] = value
        if "worktree" not in fields or "prunable" in fields:
            continue
        branch = fields.get("branch")
        found.append(
            Checkout(
                Path(fields["worktree"]),
                None if branch is None else branch.removeprefix(BRANCH_REF),
            )
        )
    return found


async def _tips(path: Path) -> dict[str, str]:
    """Each local branch's commit."""
    output = await run_hardened_git(
        ["for-each-ref", "--format=%(refname)%00%(objectname)", BRANCH_REF], path
    )
    tips: dict[str, str] = {}
    for line in output.splitlines():
        ref, _, commit = line.partition("\0")
        tips[ref.removeprefix(BRANCH_REF)] = commit
    return tips


async def _ahead(path: Path, shown: Sequence[Candidate]) -> dict[tuple[str, str], int]:
    """`c..b` counted for every pair of shown branches, in one git command."""
    atoms = "".join(f"%00%(ahead-behind:{candidate.tip})" for candidate in shown)
    refs = [f"{BRANCH_REF}{candidate.name}" for candidate in shown]
    output = await run_hardened_git(["for-each-ref", f"--format=%(refname){atoms}", *refs], path)
    ahead: dict[tuple[str, str], int] = {}
    for line in output.splitlines():
        ref, *counts = line.split("\0")
        name = ref.removeprefix(BRANCH_REF)
        for other, count in zip(shown, counts, strict=True):
            ahead[(name, other.name)] = int(count.split(" ")[0])
    return ahead


def _owner(repo_path: Path, path: Path) -> Owner:
    if path.parent != claude_worktrees_dir(repo_path):
        return "other"
    return "nest" if path.name.startswith(OWNED_WORKTREE_PREFIXES) else "claude"
