"""Which branch each branch of the map hangs from (B96), on made-up distances."""

from pathlib import Path

from nestd.repos.branch_map import Candidate, MapWorktree, arrange


def nest(name: str) -> MapWorktree:
    return MapWorktree(path=Path(f"/r/.claude/worktrees/nest-{name}"), owner="nest")


def other(name: str) -> MapWorktree:
    return MapWorktree(path=Path(f"/elsewhere/{name}"), owner="other")


def distances(rows: dict[str, dict[str, int]]) -> dict[tuple[str, str], int]:
    """`rows[b][c]` is how many commits of `b` are not in `c`; a branch is 0 from itself."""
    table = {(b, c): count for b, row in rows.items() for c, count in row.items()}
    return table | {(b, b): 0 for b in rows}


def test_the_parent_is_the_branch_with_the_nearest_fork_point() -> None:
    candidates = [
        Candidate("main", "m"),
        Candidate("wip", "w"),
        Candidate("agent/icons", "i", nest("1"), base="w"),
        Candidate("deep", "d", other("deep")),
    ]
    ahead = distances(
        {
            "main": {"wip": 0, "agent/icons": 0, "deep": 0},
            "wip": {"main": 2, "agent/icons": 0, "deep": 0},
            "agent/icons": {"main": 3, "wip": 1, "deep": 1},
            "deep": {"main": 5, "wip": 3, "agent/icons": 2},
        }
    )

    assert arrange("main", candidates, ahead) == [
        ("main", None),
        ("wip", "main"),
        ("agent/icons", "wip"),
        ("deep", "agent/icons"),
    ]


def test_ties_go_to_the_root_then_the_recorded_base_then_the_nearest_to_the_root() -> None:
    # `x` is as near to main as to `a`; `y` was started at `b`'s commit, as near to both.
    candidates = [
        Candidate("main", "m"),
        Candidate("a", "ta", other("a")),
        Candidate("b", "tb", other("b")),
        Candidate("x", "tx", other("x")),
        Candidate("y", "ty", nest("y"), base="tb"),
        Candidate("z", "tz", nest("z")),
    ]
    ahead = distances(
        {
            "main": {"a": 0, "b": 0, "x": 0, "y": 0, "z": 0},
            "a": {"main": 1, "b": 1, "x": 1, "y": 1, "z": 1},
            "b": {"main": 1, "a": 1, "x": 1, "y": 1, "z": 1},
            "x": {"main": 2, "a": 2, "b": 2, "y": 2, "z": 2},
            "y": {"main": 3, "a": 2, "b": 2, "x": 3, "z": 3},
            # As near to `a`, `b` and `y`: `a` and `b` are nearer the root, `a` first by name.
            "z": {"main": 4, "a": 3, "b": 3, "x": 4, "y": 3},
        }
    )

    assert arrange("main", candidates, ahead) == [
        ("main", None),
        ("a", "main"),
        ("z", "a"),
        ("b", "main"),
        ("y", "b"),
        ("x", "main"),
    ]


def test_a_fresh_worktree_hangs_from_the_branch_it_was_started_from() -> None:
    # Nothing committed yet: both are as far from main as `wip`, and the same commit.
    candidates = [
        Candidate("main", "m"),
        Candidate("wip", "w"),
        Candidate("agent/a", "w", nest("a"), base="w"),
        Candidate("agent/b", "w", nest("b"), base="w"),
    ]
    ahead = distances(
        {
            "main": {"wip": 0, "agent/a": 0, "agent/b": 0},
            "wip": {"main": 2, "agent/a": 0, "agent/b": 0},
            "agent/a": {"main": 2, "wip": 0, "agent/b": 0},
            "agent/b": {"main": 2, "wip": 0, "agent/a": 0},
        }
    )

    assert arrange("main", candidates, ahead) == [
        ("main", None),
        ("wip", "main"),
        ("agent/a", "wip"),
        ("agent/b", "wip"),
    ]


def test_branches_at_one_commit_never_hang_from_each_other_in_a_cycle() -> None:
    # Every pair is 0 apart: only the order nearest-the-root, then kind, then name decides.
    candidates = [
        Candidate("main", "m"),
        Candidate("q", "t", other("q")),
        Candidate("p", "t", other("p")),
        Candidate("n", "t", nest("n")),
    ]
    ahead = distances(
        {
            "main": {"q": 0, "p": 0, "n": 0},
            "q": {"main": 1, "p": 0, "n": 0},
            "p": {"main": 1, "q": 0, "n": 0},
            "n": {"main": 1, "q": 0, "p": 0},
        }
    )

    result = arrange("main", candidates, ahead)

    assert result == [("main", None), ("p", "main"), ("n", "p"), ("q", "p")]


def test_a_branch_behind_the_root_hangs_from_the_root() -> None:
    candidates = [Candidate("main", "m"), Candidate("old", "o", other("old"))]
    ahead = distances({"main": {"old": 3}, "old": {"main": 0}})

    assert arrange("main", candidates, ahead) == [("main", None), ("old", "main")]


def test_a_lone_root() -> None:
    assert arrange("main", [Candidate("main", "m")], {("main", "main"): 0}) == [("main", None)]
