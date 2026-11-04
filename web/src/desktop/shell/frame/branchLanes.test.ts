// Ported from NestKitTests' BranchMapTests (B96): the lanes and each branch's chat dot.
import { describe, expect, it } from "vitest";
import type { BranchMap, BranchMapBranch } from "../../../api/types.ts";
import { repo, session } from "../../../test/fixtures.ts";
import { branchChats, branchLanes } from "./branchLanes.ts";

function branch(name: string, parent: string | null, worktree?: string, here = false) {
  return {
    name,
    parent,
    worktree: worktree === undefined ? null : { path: worktree, owner: "nest" as const },
    here,
  } satisfies BranchMapBranch;
}

const map = (branches: BranchMapBranch[]): BranchMap => ({
  default_branch: "main",
  current_branch: null,
  branches,
});

// main, wip (where the project folder is) with three worktrees, and two worktrees from main.
const fixture = map([
  branch("main", null),
  branch("b94-codex-settings", "main", "/r/.claude/worktrees/nest-b94"),
  branch("lazy-scroll", "main", "/r/.claude/worktrees/lazy"),
  branch("wip", "main", undefined, true),
  branch("pixie-search", "wip", "/r/.claude/worktrees/nest-pixie"),
  branch("wip-icons", "wip", "/elsewhere/icons"),
  branch("wip-limits", "wip", "/r/.claude/worktrees/nest-limits"),
]);

describe("the branch map's lanes", () => {
  it("lays out every branch depth first, each lane down to its last child", () => {
    const lanes = branchLanes(fixture);
    expect(lanes.rows.map((r) => r.branch.name)).toEqual([
      "main",
      "b94-codex-settings",
      "lazy-scroll",
      "wip",
      "pixie-search",
      "wip-icons",
      "wip-limits",
    ]);
    expect(lanes.rows.map((r) => r.depth)).toEqual([0, 1, 1, 1, 2, 2, 2]);
    const main = { depth: 0, lane: "main", fromMiddle: false };
    const wip = { depth: 1, lane: "wip", fromMiddle: false };
    expect(lanes.rows.map((r) => r.lines)).toEqual([
      [{ depth: 0, lane: "main", fromMiddle: true }],
      [main],
      [main],
      [{ depth: 1, lane: "wip", fromMiddle: true }],
      [wip],
      [wip],
      [],
    ]);
    expect(lanes.rows.map((r) => r.label)).toEqual([null, null, null, "here", null, null, null]);
    expect(lanes.count).toBe("5 worktrees");
    expect(lanes.width).toBe(56);
  });

  it("keeps deeper branches in their lanes and widens the graph", () => {
    const lanes = branchLanes(
      map([
        branch("main", null),
        branch("a", "main"),
        branch("b", "a"),
        branch("c", "b", "/c"),
        branch("d", "a", "/d"),
      ]),
    );
    expect(lanes.rows.map((r) => r.depth)).toEqual([0, 1, 2, 3, 2]);
    expect(lanes.rows.map((r) => r.lines)).toEqual([
      [{ depth: 0, lane: "main", fromMiddle: true }],
      [{ depth: 1, lane: "a", fromMiddle: true }],
      [
        { depth: 1, lane: "a", fromMiddle: false },
        { depth: 2, lane: "b", fromMiddle: true },
      ],
      [{ depth: 1, lane: "a", fromMiddle: false }],
      [],
    ]);
    expect(lanes.width).toBe(70);
    expect(branchLanes(map([branch("main", null), branch("x", "main", "/x")])).count).toBe(
      "1 worktree",
    );
  });

  it("still shows orphans and loops, as roots", () => {
    const lanes = branchLanes(
      map([branch("main", null), branch("orphan", "missing"), branch("x", "y"), branch("y", "x")]),
    );
    expect(lanes.rows.map((r) => r.branch.name)).toEqual(["main", "orphan", "x", "y"]);
    expect(lanes.rows.map((r) => r.depth)).toEqual([0, 0, 0, 1]);
    expect(branchLanes(map([])).width).toBe(28);
  });
});

describe("a branch's chat dot", () => {
  const here = { ...repo("todo-ui"), path: "/r", current_branch: "wip" };
  const tone = (s: ReturnType<typeof session>) =>
    s.state === "running" ? "run" : s.state === "waiting" ? "wait" : "idle";

  it("shows the most urgent of the chats in its worktree or on it, in-place ones on here", () => {
    const found = branchChats(
      fixture,
      [
        session({ id: "run", branch: "wip-icons", worktree_path: null, state: "running" }),
        session({ id: "ask", branch: "wip-icons", worktree_path: null, state: "waiting" }),
        session({ id: "px", worktree_path: "/r/.claude/worktrees/nest-pixie", branch: "x" }),
        session({ id: "folder", mode: "in_place", worktree_path: null, cwd: "/r" }),
        session({ id: "old", branch: "lazy-scroll", archived_at: "2026-10-01T10:00:00Z" }),
      ],
      [],
      here,
      tone,
    );
    expect(found.get("wip-icons")).toBe("needsYou");
    expect(found.get("pixie-search")).toBe("idle");
    expect(found.get("wip")).toBe("idle");
    expect(found.has("lazy-scroll")).toBe(false);
    expect(found.has("main")).toBe(false);
  });

  it("leaves a kept worktree when its chat moves, and follows the folder in place (B119)", () => {
    const left = {
      path: "/r/.claude/worktrees/lazy",
      branch: "lazy-scroll",
      base_ref: "abc",
      started_at: "2026-11-04T10:00:00Z",
      ended_at: "2026-11-04T11:00:00Z",
      state: "kept" as const,
    };
    const found = branchChats(
      fixture,
      [
        session({
          id: "moved",
          worktree_path: "/r/.claude/worktrees/nest-b94",
          branch: "b94-codex-settings",
          earlier_worktrees: [left],
          state: "running",
        }),
        session({
          id: "removed",
          mode: "in_place",
          worktree_path: null,
          branch: null,
          cwd: "/r",
          earlier_worktrees: [{ ...left, branch: "wip-limits", state: "deleted" }],
          state: "waiting",
        }),
      ],
      [],
      here,
      tone,
    );
    expect(found.has("lazy-scroll")).toBe(false);
    expect(found.has("wip-limits")).toBe(false);
    expect(found.get("b94-codex-settings")).toBe("running");
    expect(found.get("wip")).toBe("needsYou");
  });
});
