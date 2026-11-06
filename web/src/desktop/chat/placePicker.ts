// Where a new chat works (B55, B96, B131), ported from NestKit's ChatPlace.swift
// (NewChatChoice, NewChatPlace), PlacePicker.swift and LaneColors: the "Work on" picker built
// from the project's branch map, and where a new chat starts from the selected place.
import type {
  BranchMap,
  BranchMapBranch,
  CreateSessionBody,
  RepoConfig,
  SelectedPlace,
  SelectPlaceBody,
} from "../../api/types.ts";
import {
  branchLanes,
  INDENT_CAP,
  type BranchLanes,
  type LaneRow,
} from "../shell/frame/branchLanes.ts";

export type NewChatChoice =
  | { kind: "inPlace" }
  // `from` null: the folder's current branch.
  | { kind: "newWorktree"; from: string | null }
  | { kind: "worktree"; path: string; branch: string }
  | { kind: "onBranch"; branch: string };

export const IN_PLACE: NewChatChoice = { kind: "inPlace" };

/**
 * Where a new chat starts with no pick of its own (B131): the selected place through the
 * mode the defaults set (D038), Autopilot counting as worktree. A selected branch asks for
 * that branch even when it is the folder's, so a folder moved in a terminal is not worked on.
 */
export function selectedChoice(
  selected: SelectedPlace | null,
  mode: "in_place" | "worktree",
): NewChatChoice {
  if (selected?.worktree_path != null) {
    return { kind: "worktree", path: selected.worktree_path, branch: selected.branch };
  }
  if (mode === "worktree") return { kind: "newWorktree", from: selected?.branch ?? null };
  return selected === null ? IN_PLACE : { kind: "onBranch", branch: selected.branch };
}

export function sameChoice(a: NewChatChoice, b: NewChatChoice): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * What a choice shows as: a new worktree from no named branch starts from the folder's, and
 * the folder's own branch is the folder. For display only; the request keeps the choice.
 */
export function resolvedChoice(choice: NewChatChoice, repo: RepoConfig | undefined): NewChatChoice {
  if (choice.kind === "newWorktree" && choice.from === null && repo?.current_branch != null) {
    return { kind: "newWorktree", from: repo.current_branch };
  }
  if (choice.kind === "onBranch" && choice.branch === repo?.current_branch) return IN_PLACE;
  return choice;
}

/** Whether the picker marks this branch as where the choice starts. */
export function isSelected(
  branch: BranchMapBranch,
  choice: NewChatChoice,
  repo: RepoConfig | undefined,
): boolean {
  const shown = resolvedChoice(choice, repo);
  switch (shown.kind) {
    case "inPlace":
      return branch.here;
    case "newWorktree":
      return shown.from === branch.name;
    case "worktree":
      return shown.path === branch.worktree?.path;
    case "onBranch":
      return shown.branch === branch.name;
  }
}

export const WORKTREE_TITLE = "New worktree";
export const WORKTREE_DETAIL = "A separate copy of the project on its own new branch";

export function inPlaceTitle(repo: RepoConfig | undefined): string {
  return repo?.current_branch == null ? "Work in this folder" : `Work on ${repo.current_branch}`;
}

export function inPlaceDetail(repo: RepoConfig | undefined): string {
  return repo?.current_branch == null
    ? "Edits the project folder"
    : `Edits the project folder, on ${repo.current_branch}`;
}

/** The composer's button: "Work on wip", "New worktree from main", or a worktree's branch. */
export function choiceTitle(choice: NewChatChoice, repo: RepoConfig | undefined): string {
  switch (choice.kind) {
    case "inPlace":
      return inPlaceTitle(repo);
    case "newWorktree": {
      const from = choice.from ?? repo?.current_branch ?? null;
      return from === null ? WORKTREE_TITLE : `New worktree from ${from}`;
    }
    case "worktree":
      return choice.branch;
    case "onBranch":
      return `Work on ${choice.branch}`;
  }
}

export type PlaceBody = Pick<
  CreateSessionBody,
  "mode" | "base" | "branch" | "worktree_path" | "on_branch"
>;

/** What the new chat's request says about where it works; a plain folder works in place. */
export function placeBody(
  picked: NewChatChoice,
  typed: string,
  repo: RepoConfig | undefined,
): PlaceBody {
  const choice = repo?.git === false ? IN_PLACE : picked;
  const name = typed.trim();
  switch (choice.kind) {
    case "inPlace":
      return { mode: "in_place" };
    case "newWorktree": {
      const base = choice.from ?? repo?.current_branch ?? null;
      return {
        mode: "worktree",
        ...(base === null ? {} : { base }),
        ...(name === "" ? {} : { branch: name }),
      };
    }
    case "worktree":
      return { mode: "worktree", worktree_path: choice.path };
    case "onBranch":
      // The daemon works in place when it is the folder's branch by then.
      return { on_branch: choice.branch };
  }
}

/** What selecting a row of the map asks the daemon for. */
export function selectionOf(branch: BranchMapBranch): SelectPlaceBody {
  return branch.worktree === null
    ? { branch: branch.name }
    : { worktree_path: branch.worktree.path };
}

/** Where a click on a row of the picker works, for that one chat. */
export function branchChoice(branch: BranchMapBranch): NewChatChoice {
  if (branch.here) return IN_PLACE;
  if (branch.worktree !== null) {
    return { kind: "worktree", path: branch.worktree.path, branch: branch.name };
  }
  return { kind: "onBranch", branch: branch.name };
}

export type PickerRow = LaneRow & {
  choice: NewChatChoice;
  // "New worktree from" this row; a remote-only row has none.
  newWorktree: NewChatChoice | null;
  // What the row says to a screen reader.
  words: string;
};

export const ROW_HEIGHT = 30;
// The rows that show under the pinned top row; the rest scroll.
export const VISIBLE_ROWS = 8;

function rowWords(branch: BranchMapBranch): string {
  if (branch.here) return `Work on ${branch.name} in the project folder`;
  if (branch.worktree !== null) return `Work in worktree ${branch.name}`;
  return `Work on ${branch.name}, branch`;
}

/** The "Work on" picker: the top row pinned, every other branch under it in its lane. */
export class PlacePicker {
  readonly lanes: BranchLanes;
  readonly top: PickerRow | null;
  readonly rows: PickerRow[];

  constructor(map: BranchMap) {
    this.lanes = branchLanes(map, INDENT_CAP);
    const row = (lane: LaneRow): PickerRow => ({
      ...lane,
      choice: branchChoice(lane.branch),
      newWorktree:
        lane.branch.remote === null ? { kind: "newWorktree", from: lane.branch.name } : null,
      words: rowWords(lane.branch),
    });
    this.top = this.lanes.top === null ? null : row(this.lanes.top);
    this.rows = this.lanes.rest.map(row);
  }
}

export const LANES = ["root", "violet", "teal", "blue", "pink", "lime", "orange", "yellow"];

const topBranch = (map: BranchMap) => map.branches.find((b) => b.parent === null)?.name;

/** Where a project's lane colours are kept between runs. */
export interface LaneMemory {
  saved: Record<string, number>;
  save: (colours: Record<string, number>) => void;
}

/**
 * The lane colours of a project's branches, as NestKit's LaneColors: the top row grey, the
 * others the first colour no shown branch uses, cycling once all are in use. A plain branch
 * takes no colour of its own until something asks for one (see rowLane). A branch keeps its
 * colour for as long as it is on the map: the colours are kept, because giving them out
 * again by position would change them when the app starts or another branch appears.
 */
export class LaneColors {
  private readonly assigned: Map<string, number>;
  private readonly memory: LaneMemory | null;
  private cycle = 0;

  constructor(memory: LaneMemory | null = null) {
    this.memory = memory;
    this.assigned = new Map(Object.entries(memory?.saved ?? {}));
  }

  assign(map: BranchMap): void {
    const parents = new Set(map.branches.map((b) => b.parent));
    for (const branch of map.branches) {
      if (branch.worktree !== null || parents.has(branch.name)) this.index(branch.name, map);
    }
  }

  /** The branch's palette index: 0 for the top row, else its colour, given the first time. */
  index(branch: string, map: BranchMap): number {
    if (branch === topBranch(map)) return 0;
    return this.assigned.get(branch) ?? this.give(branch, map);
  }

  private give(branch: string, map: BranchMap): number {
    const used = new Set(
      map.branches.flatMap((b) => {
        const index = this.assigned.get(b.name);
        return index === undefined ? [] : [index];
      }),
    );
    let index = -1;
    for (let colour = 1; colour < LANES.length; colour++) {
      if (!used.has(colour)) {
        index = colour;
        break;
      }
    }
    if (index === -1) {
      index = (this.cycle % (LANES.length - 1)) + 1;
      this.cycle += 1;
    }
    this.assigned.set(branch, index);
    this.memory?.save(
      Object.fromEntries(
        map.branches.flatMap((b) => {
          const colour = this.assigned.get(b.name);
          return colour === undefined ? [] : [[b.name, colour]];
        }),
      ),
    );
    return index;
  }
}

/** A palette index's CSS colour. */
export const laneColor = (index: number) => `var(--lane-${LANES[index % LANES.length] ?? "root"})`;
