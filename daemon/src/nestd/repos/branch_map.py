"""A git project's branch map (B96, B131): every local branch, each hanging from the branch
it comes from, under the top row, and the branches only a remote has.
"""

import asyncio
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from nestd.config.models import RepoConfig
from nestd.gitops.hardened import remote_names, run_hardened_git
from nestd.gitops.remotes import REMOTE
from nestd.repos.service import BRANCH_REF, REMOTE_REF
from nestd.worktrees.options import claude_worktrees_dir
from nestd.worktrees.ownership import is_nest_worktree

type Owner = Literal["nest", "claude", "other"]
# Among branches as far from the root, the branch of the project folder (or of no
# worktree) comes first, then other worktrees', then Nest's, which are seldom bases.
_KIND_ORDER: Mapping[Owner | None, int] = {None: 0, "claude": 1, "other": 1, "nest": 2}
# Comparing every branch with every other grows with the square of the branches, so past
# this many the rest can only hang from these.
MAX_BASES = 200
_TOP_NAME = "main"
_OLD_TOP_NAME = "master"
_BEHIND = re.compile(r"behind (\d+)")


class MapWorktree(BaseModel):
    path: Path
    # Nest's own (B141 `is_nest_worktree`), Claude Code's (elsewhere in `.claude/worktrees/`)
    # or other.
    owner: Owner


class MapBranch(BaseModel):
    name: str
    # Null for the root only.
    parent: str | None
    # The linked worktree the branch is checked out in.
    worktree: MapWorktree | None
    # The branch the project folder is on.
    here: bool
    # Commits its remote branch has that it lacks, as of the last fetch.
    behind: int = 0
    # The remote it is on, for a top row with no local branch; null for the rest.
    remote: str | None = None


class RemoteBranch(BaseModel):
    remote: str
    name: str


class BranchMap(BaseModel):
    default_branch: str | None
    # Null when the project folder is on a detached HEAD or a branch without commits.
    current_branch: str | None
    # The project folder is on a detached HEAD, as git says; false when in doubt.
    detached: bool = False
    # Depth first from the top row, then as in `arrange`.
    branches: list[MapBranch]
    # Branches with no local branch of their name, by remote, `origin` first. The remote-only
    # top row is not among them.
    remote_branches: list[RemoteBranch]


@dataclass(frozen=True)
class Candidate:
    """A branch to place: its tip commit, its worktree, the commit Nest started that
    worktree's chat from, when it did, its commit time, and its remote when it has no local
    branch.
    """

    name: str
    tip: str
    worktree: MapWorktree | None = None
    base: str | None = None
    time: int = 0
    remote: str | None = None

    @property
    def ref(self) -> str:
        if self.remote is None:
            return f"{BRANCH_REF}{self.name}"
        return f"{REMOTE_REF}{self.remote}/{self.name}"


def arrange(
    root: str,
    candidates: Sequence[Candidate],
    ahead: Mapping[tuple[str, str], int],
    here: str | None = None,
) -> list[tuple[str, str | None]]:
    """Each branch with its parent, depth first from `root`. Siblings: `here`, the project
    folder's branch, then branches with a worktree or children, then by name.

    `ahead[(b, c)]` counts the commits of `b` that `c` does not have (`c..b`). A branch's
    parent is the branch it has fewest commits beyond: its nearest fork point. Ties go to
    the root, then to the branch at the commit Nest started the worktree from, then to
    the one first in the order below. `ahead` may leave out some `c` (see `MAX_BASES`), but
    not the root; those cannot be parents.

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
            if other.name == root
            or (
                (branch.name, other.name) in ahead
                and other.name != branch.name
                and order(other) < order(branch)
            )
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
    worktrees = {candidate.name for candidate in candidates if candidate.worktree is not None}

    def sibling_order(name: str) -> tuple[bool, bool, str]:
        return (name != here, name not in worktrees and not children[name], name)

    placed: list[tuple[str, str | None]] = []
    pending: list[tuple[str, str | None]] = [(root, None)]
    while pending:
        name, parent = pending.pop()
        placed.append((name, parent))
        pending += [
            (child, name) for child in sorted(children[name], key=sibling_order, reverse=True)
        ]
    return placed


@dataclass(frozen=True)
class Checkout:
    path: Path
    branch: str | None
    detached: bool = False


@dataclass(frozen=True)
class _Ref:
    tip: str
    time: int
    behind: int = 0


@dataclass(frozen=True)
class _Refs:
    heads: dict[str, _Ref]
    # Each configured remote's branches, `origin` first.
    remotes: dict[str, dict[str, _Ref]]
    # The branch each remote's `HEAD` points to, when it is set and that ref exists.
    remote_heads: dict[str, str]


async def read_branch_map(
    repo: RepoConfig, bases: Mapping[Path, str], *, fork_points: bool = False
) -> BranchMap:
    """The map of a git repo whose folder exists; `bases` maps the worktree paths of Nest's
    chats to the commits they started from.

    With `fork_points`, only the default branch, the folder's and the worktrees' are placed,
    from the default branch: the reviewed work of a chat is measured from these, and must
    not shrink because a nearer branch exists, such as a backup. No remotes are read.
    """
    main, *linked = await checkouts(repo.path)
    refs = await _read_refs(repo.path, [] if fork_points else await remote_names(repo.path))
    heads = refs.heads
    current = main.branch if main.branch in heads else None
    worktrees: dict[str, Checkout] = {}
    for checkout in linked:
        branch = checkout.branch
        if branch is not None and branch in heads and branch != main.branch:
            worktrees.setdefault(branch, checkout)
    owners = await asyncio.to_thread(_owners, repo.path, list(worktrees.values()))

    def local(name: str) -> Candidate:
        head, checkout = heads[name], worktrees.get(name)
        if checkout is None:
            return Candidate(name, head.tip, time=head.time)
        worktree = MapWorktree(path=checkout.path, owner=owners[checkout.path])
        return Candidate(name, head.tip, worktree, bases.get(checkout.path), head.time)

    default = repo.default_branch
    remote_branches: list[RemoteBranch] = []
    if fork_points:
        named = (default, current, *worktrees)
        shown = {name: local(name) for name in named if name is not None and name in heads}
        root = _old_root(shown, default, current)
    else:
        shown = {name: local(name) for name in heads}
        root, remote = _top_branch(refs, default, current)
        if root is not None and remote is not None:
            ref = refs.remotes[remote][root]
            shown[root] = Candidate(root, ref.tip, time=ref.time, remote=remote)
        remote_branches = _remote_only(refs, root, remote)
    if root is None:
        return BranchMap(
            default_branch=default,
            current_branch=current,
            detached=main.detached,
            branches=[],
            remote_branches=remote_branches,
        )
    candidates = list(shown.values())
    ahead = await _ahead(repo.path, candidates, _bases(candidates, root, current))
    return BranchMap(
        default_branch=default,
        current_branch=current,
        detached=main.detached,
        branches=[
            MapBranch(
                name=name,
                parent=parent,
                worktree=shown[name].worktree,
                here=name == current,
                behind=heads[name].behind if name in heads else 0,
                remote=shown[name].remote,
            )
            for name, parent in arrange(root, candidates, ahead, current)
        ],
        remote_branches=remote_branches,
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
                "detached" in fields,
            )
        )
    return found


async def _read_refs(path: Path, remotes: Sequence[str]) -> _Refs:
    """All local branches, and the branches of the configured `remotes`, in one git command.
    A `HEAD` pointing at a branch that is gone is not listed, so it stays unknown.
    """
    atoms = ("refname", "objectname", "committerdate:unix", "symref", "upstream")
    fields = "%00".join(f"%({atom})" for atom in (*atoms, "upstream:track,nobracket"))
    output = await run_hardened_git(
        ["for-each-ref", f"--format={fields}", BRANCH_REF, REMOTE_REF], path
    )
    heads: dict[str, _Ref] = {}
    ordered = sorted(remotes, key=lambda remote: (remote != REMOTE, remote))
    branches: dict[str, dict[str, _Ref]] = {remote: {} for remote in ordered}
    remote_heads: dict[str, str] = {}
    for line in filter(None, output.split("\n")):
        ref, tip, time, symref, upstream, track = line.split("\0")
        moment = int(time or 0)
        if ref.startswith(BRANCH_REF):
            heads[ref.removeprefix(BRANCH_REF)] = _Ref(tip, moment, _behind(upstream, track))
            continue
        found = _split_remote_ref(ref, remotes)
        if found is None:
            continue
        remote, name = found
        if name == "HEAD":
            remote_heads[remote] = symref.removeprefix(f"{REMOTE_REF}{remote}/")
        elif not symref:
            branches[remote][name] = _Ref(tip, moment)
    return _Refs(heads, branches, remote_heads)


def _behind(upstream: str, track: str) -> int:
    """How far a branch is behind its remote branch, from `%(upstream:track,nobracket)`: such
    as `behind 3`, `ahead 1, behind 1`, or `gone`. Tracking a local branch is not counted.
    """
    found = _BEHIND.search(track) if upstream.startswith(REMOTE_REF) else None
    return 0 if found is None else int(found.group(1))


def _split_remote_ref(ref: str, remotes: Sequence[str]) -> tuple[str, str] | None:
    """(remote, branch) of a tracking ref, by the longest remote name that fits: both can
    hold slashes. None for a remote no longer configured.
    """
    fitting = [remote for remote in remotes if ref.startswith(f"{REMOTE_REF}{remote}/")]
    if not fitting:
        return None
    remote = max(fitting, key=len)
    return remote, ref.removeprefix(f"{REMOTE_REF}{remote}/")


def _top_branch(
    refs: _Refs, default: str | None, current: str | None
) -> tuple[str | None, str | None]:
    """The map's top row and, when it has no local branch, its remote. The first that
    exists wins: a local `main`; `main` on a remote; what a remote's `HEAD` points to; a local
    `master`; the default branch setting; the folder's branch; the first by name. It sets
    only the map's order, never where a chat starts.
    """
    heads = refs.heads
    if _TOP_NAME in heads:
        return _TOP_NAME, None
    for remote, branches in refs.remotes.items():
        if _TOP_NAME in branches:
            return _TOP_NAME, remote
    for remote, branches in refs.remotes.items():
        name = refs.remote_heads.get(remote)
        if name is not None and name in branches:
            return name, None if name in heads else remote
    for name in (_OLD_TOP_NAME, default, current):
        if name is not None and name in heads:
            return name, None
    return min(heads, default=None), None


def _old_root(
    shown: Mapping[str, Candidate], default: str | None, current: str | None
) -> str | None:
    if default is not None and default in shown:
        return default
    return current if current is not None else min(shown, default=None)


def _remote_only(refs: _Refs, top: str | None, top_remote: str | None) -> list[RemoteBranch]:
    return [
        RemoteBranch(remote=remote, name=name)
        for remote, branches in refs.remotes.items()
        for name in sorted(branches)
        if name not in refs.heads and (name, remote) != (top, top_remote)
    ]


def _bases(candidates: Sequence[Candidate], root: str, current: str | None) -> list[Candidate]:
    """The branches others may hang from, at most `MAX_BASES`: the root, the folder's, the
    worktrees', then the newest.
    """

    def rank(candidate: Candidate) -> tuple[bool, bool, bool, int, str]:
        return (
            candidate.name != root,
            candidate.name != current,
            candidate.worktree is None,
            -candidate.time,
            candidate.name,
        )

    return sorted(candidates, key=rank)[:MAX_BASES]


async def _ahead(
    path: Path, shown: Sequence[Candidate], bases: Sequence[Candidate]
) -> dict[tuple[str, str], int]:
    """`c..b` counted for every shown branch `b` and every `c` of `bases`, in one git
    command.
    """
    atoms = "".join(f"%00%(ahead-behind:{base.tip})" for base in bases)
    names = {candidate.ref: candidate.name for candidate in shown}
    output = await run_hardened_git(["for-each-ref", f"--format=%(refname){atoms}", *names], path)
    ahead: dict[tuple[str, str], int] = {}
    for line in output.splitlines():
        ref, *counts = line.split("\0")
        for base, count in zip(bases, counts, strict=True):
            ahead[(names[ref], base.name)] = int(count.split(" ")[0])
    return ahead


def _owners(repo_path: Path, checkouts: list[Checkout]) -> dict[Path, Owner]:
    return {checkout.path: _owner(repo_path, checkout.path) for checkout in checkouts}


def _owner(repo_path: Path, path: Path) -> Owner:
    if is_nest_worktree(repo_path, path):
        return "nest"
    return "claude" if path.parent == claude_worktrees_dir(repo_path) else "other"
