// Ported from NestKitTests' PlacePickerTests (B96): the new chat's "Work on" picker, built
// from the project's branch map, and what each choice asks the daemon for.
import { describe, expect, it } from "vitest";
import type { BranchMap, BranchMapBranch, RepoConfig } from "../../api/types.ts";
import { repo } from "../../test/fixtures.ts";
import {
  choiceTitle,
  LaneColors,
  MAX_HEIGHT,
  PlacePicker,
  placeBody,
  type NewChatChoice,
} from "./placePicker.ts";

const wt = (path: string, owner: "nest" | "claude" | "other" = "nest") => ({ path, owner });
const fixture: BranchMap = {
  default_branch: "main",
  current_branch: "wip",
  branches: [
    { name: "main", parent: null, worktree: null, here: false },
    {
      name: "b94-codex-settings",
      parent: "main",
      worktree: wt("/r/.claude/worktrees/nest-b94"),
      here: false,
    },
    {
      name: "lazy-scroll",
      parent: "main",
      worktree: wt("/r/.claude/worktrees/lazy", "claude"),
      here: false,
    },
    { name: "wip", parent: "main", worktree: null, here: true },
    {
      name: "pixie-search",
      parent: "wip",
      worktree: wt("/r/.claude/worktrees/nest-pixie"),
      here: false,
    },
    { name: "wip-icons", parent: "wip", worktree: wt("/elsewhere/icons", "other"), here: false },
    {
      name: "wip-limits",
      parent: "wip",
      worktree: wt("/r/.claude/worktrees/nest-limits"),
      here: false,
    },
  ],
};
const branch = (name: string, parent: string | null, worktree?: string): BranchMapBranch => ({
  name,
  parent,
  worktree: worktree === undefined ? null : wt(worktree),
  here: false,
});
const mapOf = (branches: BranchMapBranch[]): BranchMap => ({
  default_branch: "main",
  current_branch: null,
  branches,
});
const line = (depth: number, lane: string, fromTop: boolean, toBottom: boolean) => ({
  depth,
  lane,
  fromTop,
  toBottom,
});

describe("the Work on picker", () => {
  it("starts with the folder's branch, then the others, each with its worktrees", () => {
    const picker = new PlacePicker(fixture);
    expect(picker.blocks.map((b) => b.id)).toEqual(["wip", "main"]);
    const wip = picker.blocks[0]?.rows ?? [];
    expect(wip.map((r) => r.id)).toEqual([
      "wip",
      "new:wip",
      "pixie-search",
      "wip-icons",
      "wip-limits",
    ]);
    expect(wip.map((r) => r.kind)).toEqual([
      "folder",
      "newWorktree",
      "worktree",
      "worktree",
      "worktree",
    ]);
    expect(wip.map((r) => r.depth)).toEqual([0, 0, 1, 1, 1]);
    expect(wip.map((r) => r.parentDepth)).toEqual([null, null, 0, 0, 0]);
    expect(wip.map((r) => r.choice)).toEqual([
      { kind: "inPlace" },
      { kind: "newWorktree", from: "wip" },
      { kind: "worktree", path: "/r/.claude/worktrees/nest-pixie", branch: "pixie-search" },
      { kind: "worktree", path: "/elsewhere/icons", branch: "wip-icons" },
      { kind: "worktree", path: "/r/.claude/worktrees/nest-limits", branch: "wip-limits" },
    ]);
    expect(wip.map((r) => r.title)).toEqual([
      "wip",
      "New worktree from wip",
      "pixie-search",
      "wip-icons",
      "wip-limits",
    ]);
    expect(wip.map((r) => r.detail)).toEqual(["project folder", null, null, null, null]);
    const trunk = line(0, "wip", true, true);
    expect(wip.map((r) => r.lines)).toEqual([
      [line(0, "wip", false, true)],
      [trunk],
      [trunk],
      [trunk],
      [],
    ]);

    const main = picker.blocks[1]?.rows ?? [];
    expect(main.map((r) => r.id)).toEqual([
      "main",
      "new:main",
      "b94-codex-settings",
      "lazy-scroll",
    ]);
    expect(main[0]?.choice).toEqual({ kind: "onBranch", branch: "main" });
    expect(main[0]?.detail).toBe("branch");
    expect(picker.width).toBe(40);
    expect(wip.map((r) => r.label)).toEqual([
      "Work on wip in the project folder",
      "New worktree from wip",
      "Work in worktree pixie-search",
      "Work in worktree wip-icons",
      "Work in worktree wip-limits",
    ]);
  });

  it("nests worktrees of worktrees, and gives an orphan a block of its own", () => {
    const picker = new PlacePicker(
      mapOf([
        branch("main", null),
        branch("a", "main", "/a"),
        branch("a2", "a", "/a2"),
        branch("b", "main"),
        branch("c", "main", "/c"),
        branch("x", "missing", "/x"),
      ]),
    );
    expect(picker.blocks.map((b) => b.id)).toEqual(["main", "b", "x"]);
    const main = picker.blocks[0]?.rows ?? [];
    expect(main.map((r) => r.id)).toEqual(["main", "new:main", "a", "a2", "c"]);
    expect(main.map((r) => r.depth)).toEqual([0, 0, 1, 2, 1]);
    expect(main.map((r) => r.parentDepth)).toEqual([null, null, 0, 1, 0]);
    const trunk = line(0, "main", true, true);
    expect(main.map((r) => r.lines)).toEqual([
      [line(0, "main", false, true)],
      [trunk],
      [trunk, line(1, "a", false, true)],
      [trunk],
      [],
    ]);
    // The lane stops at the new worktree row when nothing follows.
    expect(picker.blocks[1]?.rows.map((r) => r.lines)).toEqual([
      [line(0, "b", false, true)],
      [line(0, "b", true, false)],
    ]);
    expect(picker.blocks[2]?.rows[0]?.choice).toEqual({
      kind: "worktree",
      path: "/x",
      branch: "x",
    });
    expect(picker.width).toBe(54);
  });

  it("shows worktrees in a loop once each, and stops growing at about eleven rows", () => {
    const loop = new PlacePicker(
      mapOf([branch("main", null), branch("p", "q", "/p"), branch("q", "p", "/q")]),
    );
    expect(loop.blocks.map((b) => b.id)).toEqual(["main", "p"]);
    expect(loop.blocks[1]?.rows.map((r) => r.id)).toEqual(["p", "q"]);
    expect(new PlacePicker(mapOf([])).height).toBe(0);
    expect(new PlacePicker(fixture).height).toBe(9 * 30 + 9);
    const many = mapOf([
      branch("main", null),
      ...Array.from({ length: 20 }, (_, i) => branch(`w${String(i)}`, "main", `/w${String(i)}`)),
    ]);
    expect(new PlacePicker(many).height).toBe(MAX_HEIGHT);
  });
});

describe("where the new chat works", () => {
  const project: RepoConfig = { ...repo("todo-ui"), current_branch: "wip" };
  const choices: [NewChatChoice, string][] = [
    [{ kind: "inPlace" }, "Work on wip"],
    [{ kind: "newWorktree", from: null }, "New worktree from wip"],
    [{ kind: "newWorktree", from: "main" }, "New worktree from main"],
    [{ kind: "worktree", path: "/w/icons", branch: "wip-icons" }, "wip-icons"],
    [{ kind: "onBranch", branch: "main" }, "Work on main"],
  ];

  it("names each choice as the composer's button does", () => {
    for (const [choice, title] of choices) expect(choiceTitle(choice, project)).toBe(title);
  });

  it("asks the daemon for exactly that place", () => {
    expect(placeBody({ kind: "inPlace" }, "ignored", project)).toEqual({ mode: "in_place" });
    expect(placeBody({ kind: "newWorktree", from: null }, "  fix/copy ", project)).toEqual({
      mode: "worktree",
      base: "wip",
      branch: "fix/copy",
    });
    expect(placeBody({ kind: "newWorktree", from: "main" }, "", project)).toEqual({
      mode: "worktree",
      base: "main",
    });
    expect(
      placeBody({ kind: "worktree", path: "/w/icons", branch: "wip-icons" }, "", project),
    ).toEqual({ mode: "worktree", worktree_path: "/w/icons" });
    expect(placeBody({ kind: "onBranch", branch: "main" }, "", project)).toEqual({
      on_branch: "main",
    });
    // A plain folder always works in place.
    expect(placeBody({ kind: "onBranch", branch: "main" }, "", { ...project, git: false })).toEqual(
      {
        mode: "in_place",
      },
    );
  });
});

describe("lane colours", () => {
  it("keeps the default branch grey and gives each other branch its own colour", () => {
    const lanes = new LaneColors();
    lanes.assign(fixture);
    expect(lanes.index("main", fixture)).toBe(0);
    const others = fixture.branches
      .filter((b) => b.name !== "main")
      .map((b) => lanes.index(b.name, fixture));
    expect(new Set(others).size).toBe(others.length);
    expect(others.every((i) => i !== null && i > 0)).toBe(true);
    // A branch keeps its colour when the map is read again.
    const before = lanes.index("wip", fixture);
    lanes.assign(fixture);
    expect(lanes.index("wip", fixture)).toBe(before);
  });
});
