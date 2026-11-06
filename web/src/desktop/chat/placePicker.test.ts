// Ported from NestKitTests' PlacePickerTests (B96): the new chat's "Work on" picker, built
// from the project's branch map, and what each choice asks the daemon for.
import { describe, expect, it } from "vitest";
import type { BranchMap, BranchMapBranch, RepoConfig } from "../../api/types.ts";
import { repo } from "../../test/fixtures.ts";
import {
  choiceTitle,
  isSelected,
  LaneColors,
  PlacePicker,
  placeBody,
  resolvedChoice,
  selectedChoice,
  selectionOf,
  type LaneMemory,
  type NewChatChoice,
} from "./placePicker.ts";

const branch = (
  name: string,
  parent: string | null,
  worktree?: string,
  extra: Partial<BranchMapBranch> = {},
): BranchMapBranch => ({
  name,
  parent,
  worktree: worktree === undefined ? null : { path: worktree, owner: "nest" },
  here: false,
  behind: 0,
  remote: null,
  ...extra,
});
const mapOf = (branches: BranchMapBranch[]): BranchMap => ({
  default_branch: "main",
  current_branch: null,
  detached: false,
  branches,
  remote_branches: [],
});
const fixture: BranchMap = {
  ...mapOf([
    branch("main", null),
    branch("b94-codex-settings", "main", "/r/nest-b94"),
    branch("wip", "main", undefined, { here: true }),
    branch("pixie-search", "wip", "/r/nest-pixie"),
    branch("wip-icons", "wip", "/elsewhere/icons"),
    branch("backup", "main"),
  ]),
  current_branch: "wip",
};

describe("the Work on picker", () => {
  it("pins the top row and lists every other branch in its lane", () => {
    const picker = new PlacePicker(fixture);
    expect(picker.top?.branch.name).toBe("main");
    expect(picker.rows.map((r) => r.branch.name)).toEqual([
      "b94-codex-settings",
      "wip",
      "pixie-search",
      "wip-icons",
      "backup",
    ]);
    expect(picker.rows.map((r) => r.depth)).toEqual([1, 1, 2, 2, 1]);
    expect(picker.rows.map((r) => r.choice)).toEqual([
      { kind: "worktree", path: "/r/nest-b94", branch: "b94-codex-settings" },
      { kind: "inPlace" },
      { kind: "worktree", path: "/r/nest-pixie", branch: "pixie-search" },
      { kind: "worktree", path: "/elsewhere/icons", branch: "wip-icons" },
      { kind: "onBranch", branch: "backup" },
    ]);
    expect(picker.rows.map((r) => r.label)).toEqual([null, "here", null, null, null]);
    expect(picker.rows.map((r) => r.words)).toEqual([
      "Work in worktree b94-codex-settings",
      "Work on wip in the project folder",
      "Work in worktree pixie-search",
      "Work in worktree wip-icons",
      "Work on backup, branch",
    ]);
  });

  it("offers a new worktree from every branch and worktree, not from a remote-only row", () => {
    const picker = new PlacePicker(fixture);
    for (const row of [picker.top, ...picker.rows]) {
      expect(row?.newWorktree).toEqual({ kind: "newWorktree", from: row?.branch.name });
    }
    const remote = new PlacePicker(mapOf([branch("main", null, undefined, { remote: "origin" })]));
    expect(remote.top?.newWorktree).toBeNull();
  });

  it("stops the indent at level 3, as the small map does", () => {
    const picker = new PlacePicker(
      mapOf([
        branch("main", null),
        branch("a", "main"),
        branch("b", "a"),
        branch("c", "b"),
        branch("d", "c"),
      ]),
    );
    expect(picker.rows.map((r) => r.depth)).toEqual([1, 2, 3, 3]);
    expect(picker.rows.map((r) => r.fromParent)).toEqual([null, null, null, "c"]);
  });

  it("marks the branch a choice starts on, the folder for the folder's own branch", () => {
    const project: RepoConfig = { ...repo("todo-ui"), current_branch: "wip" };
    const marked = (choice: NewChatChoice) =>
      fixture.branches.filter((b) => isSelected(b, choice, project)).map((b) => b.name);
    expect(marked({ kind: "inPlace" })).toEqual(["wip"]);
    expect(marked({ kind: "onBranch", branch: "wip" })).toEqual(["wip"]);
    expect(marked({ kind: "onBranch", branch: "backup" })).toEqual(["backup"]);
    expect(marked({ kind: "newWorktree", from: null })).toEqual(["wip"]);
    expect(marked({ kind: "newWorktree", from: "main" })).toEqual(["main"]);
    expect(marked({ kind: "worktree", path: "/r/nest-pixie", branch: "pixie-search" })).toEqual([
      "pixie-search",
    ]);
  });
});

describe("where a new chat starts from the selected place (B131)", () => {
  const project: RepoConfig = { ...repo("todo-ui"), current_branch: "wip" };
  const onB = { branch: "feat/b", worktree_path: null };
  const inW = { branch: "feat/w", worktree_path: "/w/feat" };

  // Autopilot on counts as the worktree mode.
  it.each([
    [null, "in_place", { kind: "inPlace" }, { mode: "in_place" }],
    [null, "worktree", { kind: "newWorktree", from: null }, { mode: "worktree", base: "wip" }],
    [onB, "in_place", { kind: "onBranch", branch: "feat/b" }, { on_branch: "feat/b" }],
    [
      onB,
      "worktree",
      { kind: "newWorktree", from: "feat/b" },
      { mode: "worktree", base: "feat/b" },
    ],
    [
      inW,
      "in_place",
      { kind: "worktree", path: "/w/feat", branch: "feat/w" },
      { mode: "worktree", worktree_path: "/w/feat" },
    ],
    [
      inW,
      "worktree",
      { kind: "worktree", path: "/w/feat", branch: "feat/w" },
      { mode: "worktree", worktree_path: "/w/feat" },
    ],
  ] as const)("%j in %s", (selected, mode, choice, body) => {
    const shown = selectedChoice(selected, mode);
    expect(shown).toEqual(choice);
    expect(placeBody(shown, "", project)).toEqual(body);
  });

  it("asks for the folder's own branch by name, in case a terminal moved the folder", () => {
    const shown = selectedChoice({ branch: "wip", worktree_path: null }, "in_place");
    expect(placeBody(shown, "", project)).toEqual({ on_branch: "wip" });
    expect(resolvedChoice(shown, project)).toEqual({ kind: "inPlace" });
  });

  it("selects a row by its worktree when it has one, else by its branch", () => {
    expect(selectionOf(branch("a", "main", "/w/a"))).toEqual({ worktree_path: "/w/a" });
    expect(selectionOf(branch("a", "main"))).toEqual({ branch: "a" });
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
  it("keeps the top row grey and gives each branch that needs one its own colour", () => {
    const lanes = new LaneColors();
    lanes.assign(fixture);
    expect(lanes.index("main", fixture)).toBe(0);
    const others = ["b94-codex-settings", "wip", "pixie-search", "wip-icons"].map((name) =>
      lanes.index(name, fixture),
    );
    expect(new Set(others).size).toBe(others.length);
    expect(others.every((i) => i > 0)).toBe(true);
    // A branch keeps its colour when the map is read again.
    const before = lanes.index("wip", fixture);
    lanes.assign(fixture);
    expect(lanes.index("wip", fixture)).toBe(before);
  });

  it("follows the top row, not the default branch setting", () => {
    const map = { ...fixture, default_branch: "wip" };
    const lanes = new LaneColors();
    lanes.assign(map);
    expect(lanes.index("main", map)).toBe(0);
    expect(lanes.index("wip", map)).toBeGreaterThan(0);
  });

  it("keeps every colour across a restart, whatever appears on the map", () => {
    const memory: LaneMemory = {
      saved: {},
      save: (colours) => {
        memory.saved = colours;
      },
    };
    const first = new LaneColors(memory);
    first.assign(fixture);
    const before = ["wip", "b94-codex-settings", "pixie-search", "wip-icons"].map((name) =>
      first.index(name, fixture),
    );

    // A new branch sorted first would take the first colour if they were given by position.
    const grown = {
      ...fixture,
      branches: [
        ...fixture.branches.slice(0, 1),
        branch("a-new-one", "main", "/w/new"),
        ...fixture.branches.slice(1),
      ],
    };
    const restarted = new LaneColors(memory);
    restarted.assign(grown);

    expect(
      ["wip", "b94-codex-settings", "pixie-search", "wip-icons"].map((name) =>
        restarted.index(name, grown),
      ),
    ).toEqual(before);
    expect(before).not.toContain(restarted.index("a-new-one", grown));
  });

  it("spends no colour on a plain branch until one is asked for", () => {
    const map = mapOf([
      branch("main", null),
      ...Array.from({ length: 7 }, (_, i) => branch(`plain${String(i)}`, "main")),
      branch("worktree", "main", "/w"),
    ]);
    const lanes = new LaneColors();
    lanes.assign(map);
    expect(lanes.index("worktree", map)).toBe(1);
    expect(lanes.index("plain3", map)).toBe(2);
  });
});
