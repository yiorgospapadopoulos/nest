// The sidebar's branch map (B96, A7), ported from NestKit's BranchLanes.swift: each branch
// in its lane, joined to the branch it comes from, and each branch's chat dot.
import type {
  BranchMap,
  BranchMapBranch,
  ClaudeChat,
  RemoteBranch,
  RepoConfig,
  Session,
} from "../../../api/types.ts";
import { sessionPlace, type ChatPlace } from "../../../screens/chat/place.ts";
import type { Tone } from "../../../store/selectors.ts";

export const LANE_ROW = 34;

// Rows deeper than this sit on it in the small map and the picker, naming their parent.
export const INDENT_CAP = 3;

/** A lane's centre, from the graph's left edge. */
export const laneX = (depth: number) => 14 + 14 * depth;

/** A line through a row: a branch's lane down to its last child, from the top or its node. */
export interface LaneLine {
  depth: number;
  // The branch it belongs to, for its colour.
  lane: string;
  fromMiddle: boolean;
}

export interface LaneRow {
  branch: BranchMapBranch;
  // The lane it is drawn in, at most the cap.
  depth: number;
  lines: LaneLine[];
  // The lane its curve leaves from; its own lane past the cap, where it drops straight down.
  parentDepth: number | null;
  // Its parent's name, on rows past the cap only.
  fromParent: string | null;
  // No children and no worktree, so it wears its parent's lane until it needs its own.
  plain: boolean;
  // "here" where the project folder is.
  label: string | null;
}

export interface BranchLanes {
  rows: LaneRow[];
  // The row with no parent, pinned over the rest.
  top: LaneRow | null;
  rest: LaneRow[];
  // The graph's width: the deepest lane and a lane's room after it.
  width: number;
}

/** The branches depth first, each lane down to its last child; `maxDepth` caps the indent. */
export function branchLanes(map: BranchMap, maxDepth: number | null = null): BranchLanes {
  const names = new Set(map.branches.map((b) => b.name));
  const children = new Map<string, BranchMapBranch[]>();
  for (const branch of map.branches) {
    if (branch.parent === null || !names.has(branch.parent)) continue;
    children.set(branch.parent, [...(children.get(branch.parent) ?? []), branch]);
  }
  const placed: { branch: BranchMapBranch; depth: number }[] = [];
  const seen = new Set<string>();
  const visit = (branch: BranchMapBranch, depth: number) => {
    if (seen.has(branch.name)) return;
    seen.add(branch.name);
    placed.push({ branch, depth });
    for (const child of children.get(branch.name) ?? []) visit(child, depth + 1);
  };
  for (const branch of map.branches) {
    if (branch.parent === null || !names.has(branch.parent)) visit(branch, 0);
  }
  // A loop the daemon should never send still shows.
  for (const branch of map.branches) visit(branch, 0);

  const shown = (depth: number) => (maxDepth === null ? depth : Math.min(depth, maxDepth));
  const index = new Map(placed.map((row, at) => [row.branch.name, at]));
  const lastChild = new Map<string, number>();
  placed.forEach((row, at) => {
    const parent = row.branch.parent;
    if (parent !== null && (index.get(parent) ?? at) < at) lastChild.set(parent, at);
  });
  const lines: LaneLine[][] = placed.map(() => []);
  const add = (at: number, depth: number, lane: string, fromMiddle: boolean) => {
    const row = placed[at];
    if (row === undefined) return;
    lines[at]?.push({ depth: Math.min(depth, shown(row.depth)), lane, fromMiddle });
  };
  placed.forEach((row, at) => {
    const last = lastChild.get(row.branch.name);
    if (last === undefined) return;
    add(at, row.depth, row.branch.name, true);
    for (let between = at + 1; between < last; between++) {
      add(between, row.depth, row.branch.name, false);
    }
  });

  const rows = placed.map((row, at): LaneRow => {
    const { branch, depth } = row;
    return {
      branch,
      depth: shown(depth),
      lines: [...(lines[at] ?? [])].sort((a, b) => a.depth - b.depth),
      parentDepth: depth === 0 ? null : shown(depth - 1),
      fromParent: depth > shown(depth) ? branch.parent : null,
      plain:
        branch.worktree === null &&
        !children.has(branch.name) &&
        branch.parent !== null &&
        names.has(branch.parent),
      label: branch.here ? "here" : null,
    };
  });
  const top = rows.find((r) => r.branch.parent === null) ?? null;
  return {
    rows,
    top,
    rest: rows.filter((r) => r !== top),
    width: laneX(Math.max(0, ...rows.map((r) => r.depth))) + 14,
  };
}

/** "feat/b5…red": cut in the middle to `length` characters. */
export function middleName(name: string, length: number): string {
  if (name.length <= length) return name;
  const room = length - 1;
  return `${name.slice(0, Math.ceil(room * 0.6))}…${name.slice(-Math.floor(room * 0.4))}`;
}

export interface FoundPlaces {
  branches: BranchMapBranch[];
  remotes: RemoteBranch[];
}

const MAX_FOUND_BRANCHES = 40;
const MAX_FOUND_REMOTES = 20;

/** The branches and remote branches whose name holds `query`, with no regard for case. */
export function findPlaces(map: BranchMap, query: string): FoundPlaces {
  const wanted = query.toLowerCase();
  const holds = (name: string) => name.toLowerCase().includes(wanted);
  return {
    branches: map.branches.filter((b) => holds(b.name)).slice(0, MAX_FOUND_BRANCHES),
    remotes: map.remote_branches.filter((b) => holds(b.name)).slice(0, MAX_FOUND_REMOTES),
  };
}

// Room kept around a name brought into view sideways, so its node shows too.
const SIDE_ROOM = 44;

/**
 * A list's selected row (`.on`) comes into view, centred; a row in view moves nothing. In a
 * list that scrolls `sideways` too, its name does, ending inside the view but never starting
 * outside it.
 */
export function revealSelected(box: HTMLElement | null, sideways = false): void {
  const row = box?.querySelector(".on");
  if (box == null || row == null) return;
  const view = box.getBoundingClientRect();
  const shown = row.getBoundingClientRect();
  if (shown.top < view.top || shown.bottom > view.top + box.clientHeight) {
    box.scrollTop += shown.top - view.top - (box.clientHeight - shown.height) / 2;
  }
  const name = sideways ? row.querySelector(".fr-bmname")?.getBoundingClientRect() : undefined;
  if (name === undefined) return;
  const right = view.left + box.clientWidth;
  if (name.right > right) {
    box.scrollLeft += Math.min(name.right - right + SIDE_ROOM, name.left - view.left - SIDE_ROOM);
  } else if (name.left < view.left) {
    box.scrollLeft += name.left - view.left - SIDE_ROOM;
  }
}

/** The tint of a selected row. */
export const selectedFill = (ink: string) => ({
  background: `color-mix(in srgb, ${ink} 14%, transparent)`,
});

/** The branch a chat's place is on: a worktree by its folder first, else by name. */
export function branchFor(map: BranchMap, place: ChatPlace): BranchMapBranch | undefined {
  if (place.kind === "worktree") {
    return (
      (place.folder === null
        ? undefined
        : map.branches.find((b) => b.worktree?.path === place.folder)) ??
      map.branches.find((b) => b.name === place.name)
    );
  }
  return place.branch === null ? undefined : map.branches.find((b) => b.name === place.branch);
}

export type BranchChat = "idle" | "running" | "needsYou";

/** The lane a row draws in: its parent's while it is plain, its own once it means something. */
export function rowLane(
  row: LaneRow,
  color: (branch: string) => string | null,
  selected: boolean,
  chat: BranchChat | null,
): string {
  const borrowed = row.plain && !selected && chat === null ? row.branch.parent : null;
  return color(borrowed ?? row.branch.name) ?? "var(--t3)";
}

/** A map row's look, the same in the small map and the full tree. */
export function mapRowLook(
  row: LaneRow,
  color: (branch: string) => string | null,
  selectedBranch: string | null,
  chats: Map<string, BranchChat>,
) {
  const { branch } = row;
  const selected = branch.name === selectedBranch;
  const chat = chats.get(branch.name) ?? null;
  return {
    row,
    ink: rowLane(row, color, selected, chat),
    color,
    selected,
    chat,
    behind: branch.remote === null ? branch.behind : 0,
    addWord: branch.remote === null ? "Worktree" : null,
  };
}

const URGENCY: Record<BranchChat, number> = { idle: 0, running: 1, needsYou: 2 };

const chatOf = (tone: Tone): BranchChat =>
  tone === "run" ? "running" : tone === "wait" ? "needsYou" : "idle";

/**
 * The dot of each branch with chats (B96): the most urgent of the Nest chats in its
 * worktree folder or on it by name, and idle for the Claude Code chats in its worktree.
 * Archived chats are left out.
 */
export function branchChats(
  map: BranchMap,
  sessions: Session[],
  claudeChats: ClaudeChat[],
  repo: RepoConfig | undefined,
  tone: (session: Session) => Tone,
): Map<string, BranchChat> {
  const live = sessions.filter((s) => s.archived_at === null);
  const chats = claudeChats.filter((c) => !c.archived && c.worktree !== null);
  const byName = new Map<string, Session[]>();
  const byFolder = new Map<string, Session[]>();
  const file = (shelf: Map<string, Session[]>, key: string | null, session: Session) => {
    if (key !== null) shelf.set(key, [...(shelf.get(key) ?? []), session]);
  };
  for (const session of live) {
    const place = sessionPlace(session, repo);
    const name = place === null ? null : place.kind === "worktree" ? place.name : place.branch;
    file(byName, name, session);
    file(byFolder, session.worktree_path, session);
  }
  const found = new Map<string, BranchChat>();
  for (const branch of map.branches) {
    const path = branch.worktree?.path ?? null;
    const nest = new Set([
      ...(byName.get(branch.name) ?? []),
      ...(path === null ? [] : (byFolder.get(path) ?? [])),
    ]);
    const claude = path !== null && chats.some((c) => c.cwd === path);
    if (nest.size === 0 && !claude) continue;
    const dots = [...nest].map((s) => chatOf(tone(s)));
    found.set(
      branch.name,
      dots.reduce<BranchChat>((a, b) => (URGENCY[b] > URGENCY[a] ? b : a), "idle"),
    );
  }
  return found;
}
