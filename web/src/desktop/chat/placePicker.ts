// Where a new chat works (B55, B96), ported from NestKit's ChatPlace.swift (NewChatChoice,
// NewChatPlace), PlacePicker.swift and LaneColors: the "Work on" picker built from the
// project's branch map, a block per branch that is not a worktree, the folder's first.
import type { BranchMap, BranchMapBranch, CreateSessionBody, RepoConfig } from "../../api/types.ts";

export type NewChatChoice =
  | { kind: "inPlace" }
  // `from` null: the folder's current branch.
  | { kind: "newWorktree"; from: string | null }
  | { kind: "worktree"; path: string; branch: string }
  | { kind: "onBranch"; branch: string };

export const IN_PLACE: NewChatChoice = { kind: "inPlace" };

/** The choice a mode stands for, as the defaults and the plain menu set it (D038). */
export function choiceOfMode(mode: "in_place" | "worktree" | null): NewChatChoice {
  return mode === "worktree" ? { kind: "newWorktree", from: null } : IN_PLACE;
}

export function sameChoice(a: NewChatChoice, b: NewChatChoice): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** A new worktree from no named branch starts from the folder's, as the picker marks it. */
export function resolvedChoice(choice: NewChatChoice, repo: RepoConfig | undefined): NewChatChoice {
  if (choice.kind === "newWorktree" && choice.from === null && repo?.current_branch != null) {
    return { kind: "newWorktree", from: repo.current_branch };
  }
  return choice;
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

/** Where a click on a branch of the map starts a chat (A8). */
export function branchChoice(branch: BranchMapBranch): NewChatChoice {
  if (branch.here) return IN_PLACE;
  if (branch.worktree !== null) {
    return { kind: "worktree", path: branch.worktree.path, branch: branch.name };
  }
  return { kind: "onBranch", branch: branch.name };
}

export interface PickerLine {
  depth: number;
  // The branch the line belongs to, for its colour.
  lane: string;
  fromTop: boolean;
  toBottom: boolean;
}

export type PickerRowKind = "folder" | "branch" | "newWorktree" | "worktree";

export interface PickerRow {
  kind: PickerRowKind;
  id: string;
  // For a new worktree, the branch it starts from.
  branch: string;
  depth: number;
  lines: PickerLine[];
  // The lane the curve into a worktree's node starts from.
  parentDepth: number | null;
  choice: NewChatChoice;
  title: string;
  detail: string | null;
  label: string;
}

export interface PickerBlock {
  id: string;
  rows: PickerRow[];
}

export const ROW_HEIGHT = 30;
export const DIVIDER_HEIGHT = 9;
export const MAX_HEIGHT = 330;

/** A lane's centre, from the graph's left edge. */
export const laneX = (depth: number) => 12 + 14 * depth;

interface Entry {
  kind: PickerRowKind;
  branch: string;
  depth: number;
  parent: number | null;
  choice: NewChatChoice;
}

const children = (map: BranchMap, name: string) => map.branches.filter((b) => b.parent === name);

function rowOf(entry: Entry, lines: PickerLine[], parentDepth: number | null): PickerRow {
  const { kind, branch } = entry;
  const title = kind === "newWorktree" ? `New worktree from ${branch}` : branch;
  const label = {
    folder: `Work on ${branch} in the project folder`,
    branch: `Work on ${branch}, branch`,
    newWorktree: title,
    worktree: `Work in worktree ${branch}`,
  }[kind];
  return {
    kind,
    id: kind === "newWorktree" ? `new:${branch}` : branch,
    branch,
    depth: entry.depth,
    lines,
    parentDepth,
    choice: entry.choice,
    title,
    detail: kind === "folder" ? "project folder" : kind === "branch" ? "branch" : null,
    label,
  };
}

/** Each lane runs from its node down to its last child; a worktree's curve starts at its top. */
function rows(entries: Entry[]): PickerRow[] {
  const lines: PickerLine[][] = entries.map(() => []);
  entries.forEach((entry, index) => {
    let last = -1;
    entries.forEach((other, at) => {
      if (other.parent === index) last = at;
    });
    if (last === -1) return;
    const line = (fromTop: boolean, toBottom: boolean): PickerLine => ({
      depth: entry.depth,
      lane: entry.branch,
      fromTop,
      toBottom,
    });
    lines[index]?.push(line(false, true));
    for (let between = index + 1; between < last; between++) lines[between]?.push(line(true, true));
    if (entries[last]?.kind === "newWorktree") lines[last]?.push(line(true, false));
  });
  return entries.map((entry, index) =>
    rowOf(
      entry,
      (lines[index] ?? []).sort((a, b) => a.depth - b.depth),
      entry.kind === "worktree" && entry.parent !== null
        ? (entries[entry.parent]?.depth ?? null)
        : null,
    ),
  );
}

export class PlacePicker {
  readonly blocks: PickerBlock[];

  constructor(map: BranchMap) {
    const seen = new Set<string>();
    const blocks: PickerBlock[] = [];
    const add = (branch: BranchMapBranch, depth: number, parent: number | null, to: Entry[]) => {
      if (seen.has(branch.name)) return;
      seen.add(branch.name);
      to.push({
        kind: "worktree",
        branch: branch.name,
        depth,
        parent,
        choice: branchChoice(branch),
      });
      addWorktrees(branch.name, depth + 1, to.length - 1, to);
    };
    const addWorktrees = (name: string, depth: number, parent: number, to: Entry[]) => {
      for (const child of children(map, name)) {
        if (child.worktree !== null) add(child, depth, parent, to);
      }
    };
    const heads = map.branches.filter((b) => b.worktree === null);
    for (const head of [...heads.filter((b) => b.here), ...heads.filter((b) => !b.here)]) {
      seen.add(head.name);
      const entries: Entry[] = [
        {
          kind: head.here ? "folder" : "branch",
          branch: head.name,
          depth: 0,
          parent: null,
          choice: head.here ? IN_PLACE : { kind: "onBranch", branch: head.name },
        },
        {
          kind: "newWorktree",
          branch: head.name,
          depth: 0,
          parent: 0,
          choice: { kind: "newWorktree", from: head.name },
        },
      ];
      addWorktrees(head.name, 1, 0, entries);
      blocks.push({ id: head.name, rows: rows(entries) });
    }
    // A worktree whose parent is not shown, or a loop, still shows, in a block of its own.
    for (const branch of map.branches) {
      if (branch.worktree === null || seen.has(branch.name)) continue;
      const entries: Entry[] = [];
      add(branch, 0, null, entries);
      blocks.push({ id: branch.name, rows: rows(entries) });
    }
    this.blocks = blocks;
  }

  /** The graph's width: the deepest lane and a lane's room after it. */
  get width(): number {
    const depths = this.blocks.flatMap((b) => b.rows.map((r) => r.depth));
    return laneX(depths.length === 0 ? 0 : Math.max(...depths)) + 14;
  }

  /** As tall as the rows and dividers, up to about eleven rows; the rest scroll. */
  get height(): number {
    const count = this.blocks.reduce((sum, b) => sum + b.rows.length, 0);
    return Math.min(
      count * ROW_HEIGHT + Math.max(this.blocks.length - 1, 0) * DIVIDER_HEIGHT,
      MAX_HEIGHT,
    );
  }
}

export const LANES = ["root", "violet", "teal", "blue", "pink", "lime", "orange", "yellow"];

/**
 * The lane colours of a project's branches, as NestKit's LaneColors: the default branch
 * grey, the others the first colour no shown branch uses, cycling once all are in use. A
 * branch keeps its colour while the app runs.
 */
export class LaneColors {
  private readonly assigned = new Map<string, number>();
  private cycle = 0;

  assign(map: BranchMap): void {
    const used = new Set(
      map.branches.flatMap((b) => {
        const index = this.assigned.get(b.name);
        return index === undefined ? [] : [index];
      }),
    );
    for (const branch of map.branches) {
      if (branch.name === map.default_branch || this.assigned.has(branch.name)) continue;
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
      this.assigned.set(branch.name, index);
      used.add(index);
    }
  }

  /** The branch's palette index: 0 for the default branch, null for one never assigned. */
  index(branch: string, map: BranchMap): number | null {
    return branch === map.default_branch ? 0 : (this.assigned.get(branch) ?? null);
  }
}

/** A palette index's CSS colour. */
export const laneColor = (index: number | null) =>
  `var(--lane-${LANES[(index ?? 0) % LANES.length] ?? "root"})`;
