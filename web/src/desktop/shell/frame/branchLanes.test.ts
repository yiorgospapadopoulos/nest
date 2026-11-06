// Ported from NestKitTests' BranchMapTests (B96): the lanes and each branch's chat dot.
import { describe, expect, it } from "vitest";
import type { BranchMap, BranchMapBranch } from "../../../api/types.ts";
import { defined } from "../../../test/defined.ts";
import { repo, session } from "../../../test/fixtures.ts";
import {
  branchChats,
  branchLanes,
  findPlaces,
  middleName,
  revealSelected,
  rowLane,
} from "./branchLanes.ts";

function branch(name: string, parent: string | null, worktree?: string, here = false) {
  return {
    name,
    parent,
    worktree: worktree === undefined ? null : { path: worktree, owner: "nest" as const },
    here,
    behind: 0,
    remote: null,
  } satisfies BranchMapBranch;
}

const map = (branches: BranchMapBranch[]): BranchMap => ({
  default_branch: "main",
  current_branch: null,
  detached: false,
  branches,
  remote_branches: [],
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

describe("the indent cap (B131)", () => {
  const chain = map([
    branch("main", null),
    branch("a", "main"),
    branch("b", "a"),
    branch("c", "b"),
    branch("d", "c"),
    branch("e", "d", "/e"),
    branch("f", "e"),
  ]);

  it("keeps rows past level 3 on it, naming their parent, and the width fixed", () => {
    const capped = branchLanes(chain, 3);
    expect(capped.rows.map((r) => r.depth)).toEqual([0, 1, 2, 3, 3, 3, 3]);
    expect(capped.rows.map((r) => r.fromParent)).toEqual([null, null, null, null, "c", "d", "e"]);
    expect(capped.width).toBe(70);
    // Past the cap the row drops straight down its lane, with no lane further right.
    expect(capped.rows.map((r) => r.parentDepth)).toEqual([null, 0, 1, 2, 3, 3, 3]);
    expect(capped.rows.flatMap((r) => r.lines).every((l) => l.depth <= 3)).toBe(true);
  });

  it("has no cap in the full tree", () => {
    const tree = branchLanes(chain);
    expect(tree.rows.map((r) => r.depth)).toEqual([0, 1, 2, 3, 4, 5, 6]);
    expect(tree.rows.every((r) => r.fromParent === null)).toBe(true);
    expect(tree.width).toBe(112);
  });

  it("takes the row with no parent out of the scrolling rows, whatever the default is", () => {
    const lanes = branchLanes({ ...fixture, default_branch: "wip" });
    expect(lanes.top?.branch.name).toBe("main");
    expect(lanes.rest.map((r) => r.branch.name)).not.toContain("main");
  });

  it("lets a plain branch wear its parent's lane until it is selected or has a chat", () => {
    const lanes = branchLanes(map([branch("main", null), branch("a", "main"), branch("x", "a")]));
    const color = (name: string) => `lane-${name}`;
    const plain = lanes.rows[2];
    if (plain === undefined) throw new Error("no row");
    expect(rowLane(plain, color, false, null)).toBe("lane-a");
    expect(rowLane(plain, color, true, null)).toBe("lane-x");
    expect(rowLane(plain, color, false, "idle")).toBe("lane-x");
    // A parent, or a worktree, is never plain.
    expect(lanes.rows.map((r) => r.plain)).toEqual([false, false, true]);
  });
});

describe("the map's names", () => {
  it("cuts a long name in the middle to the length asked for", () => {
    expect(middleName("wip", 10)).toBe("wip");
    expect(middleName("feat/b53-tidy-archives", 10)).toBe("feat/b…ves");
  });

  it("finds branches and remote branches with no regard for case", () => {
    const found = findPlaces(
      {
        ...map([branch("main", null), branch("feat/Tidy", "main")]),
        remote_branches: [
          { remote: "origin", name: "fix/tidy-notes" },
          { remote: "origin", name: "fix/other" },
        ],
      },
      "tidy",
    );
    expect(found.branches.map((b) => b.name)).toEqual(["feat/Tidy"]);
    expect(found.remotes.map((b) => b.name)).toEqual(["fix/tidy-notes"]);
  });
});

describe("bringing the selected row into view", () => {
  const rect = (left: number, right: number, top: number, bottom: number) =>
    ({ left, right, top, bottom, height: bottom - top, width: right - left }) as DOMRect;
  const list = (name: DOMRect) => {
    const box = document.createElement("div");
    Object.defineProperty(box, "clientWidth", { value: 700 });
    Object.defineProperty(box, "clientHeight", { value: 400 });
    box.getBoundingClientRect = () => rect(0, 700, 0, 400);
    box.innerHTML = '<div class="on"><span class="fr-bmname"></span></div>';
    const row = defined(box.querySelector(".on"));
    row.getBoundingClientRect = () => rect(0, 1200, 100, 134);
    defined(box.querySelector(".fr-bmname")).getBoundingClientRect = () => name;
    return box;
  };

  it("leaves sideways alone unless asked, and leaves a name in view alone", () => {
    const off = list(rect(800, 900, 100, 134));
    revealSelected(off);
    expect(off.scrollLeft).toBe(0);
    const inView = list(rect(100, 300, 100, 134));
    revealSelected(inView, true);
    expect(inView.scrollLeft).toBe(0);
  });

  it("brings the end of a name cut off at the right into view", () => {
    const off = list(rect(800, 900, 100, 134));
    revealSelected(off, true);
    expect(off.scrollLeft).toBe(244);
  });

  it("keeps the start of a name too long for the view", () => {
    const long = list(rect(300, 1500, 100, 134));
    revealSelected(long, true);
    expect(long.scrollLeft).toBe(256);
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
