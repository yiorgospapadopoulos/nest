// The sidebar's branch map (B96, A7), ported from NestKit's BranchLanes.swift: each branch
// in its lane, joined to the branch it comes from, and each branch's chat dot.
import type {
  BranchMap,
  BranchMapBranch,
  ClaudeChat,
  RepoConfig,
  Session,
} from "../../../api/types.ts";
import { sessionPlace, type ChatPlace } from "../../../screens/chat/place.ts";
import type { Tone } from "../../../store/selectors.ts";

export const LANE_ROW = 34;

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
  depth: number;
  lines: LaneLine[];
  // "here" where the project folder is.
  label: string | null;
}

export interface BranchLanes {
  rows: LaneRow[];
  worktrees: number;
  // The graph's width: the deepest lane and a lane's room after it.
  width: number;
  // "5 worktrees".
  count: string;
}

export function branchLanes(map: BranchMap): BranchLanes {
  const placed: { branch: BranchMapBranch; depth: number }[] = [];
  const seen = new Set<string>();
  const visit = (branch: BranchMapBranch, depth: number) => {
    if (seen.has(branch.name)) return;
    seen.add(branch.name);
    placed.push({ branch, depth });
    for (const child of map.branches.filter((b) => b.parent === branch.name)) {
      visit(child, depth + 1);
    }
  };
  const names = new Set(map.branches.map((b) => b.name));
  for (const branch of map.branches) {
    if (branch.parent === null || !names.has(branch.parent)) visit(branch, 0);
  }
  // A loop the daemon should never send still shows.
  for (const branch of map.branches) visit(branch, 0);

  const lines: LaneLine[][] = placed.map(() => []);
  placed.forEach((row, index) => {
    let last = -1;
    placed.forEach((other, at) => {
      if (at > index && other.branch.parent === row.branch.name) last = at;
    });
    if (last === -1) return;
    lines[index]?.push({ depth: row.depth, lane: row.branch.name, fromMiddle: true });
    for (let between = index + 1; between < last; between++) {
      lines[between]?.push({ depth: row.depth, lane: row.branch.name, fromMiddle: false });
    }
  });

  const rows = placed.map((row, index) => ({
    branch: row.branch,
    depth: row.depth,
    lines: [...(lines[index] ?? [])].sort((a, b) => a.depth - b.depth),
    label: row.branch.here ? "here" : null,
  }));
  const worktrees = placed.filter((p) => p.depth > 0 && p.branch.worktree !== null).length;
  return {
    rows,
    worktrees,
    width: laneX(Math.max(0, ...rows.map((r) => r.depth))) + 14,
    count: `${String(worktrees)} worktree${worktrees === 1 ? "" : "s"}`,
  };
}

/** What a click on a row does (A8), for its tooltip and name. */
export function rowAction(branch: BranchMapBranch): string {
  if (branch.here) return "New chat in the project folder";
  if (branch.worktree !== null) return "New chat in this worktree";
  return `New chat working on ${branch.name}`;
}

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
  const found = new Map<string, BranchChat>();
  for (const branch of map.branches) {
    const path = branch.worktree?.path ?? null;
    const nest = live.filter((s) => {
      if (path !== null && s.worktree_path === path) return true;
      const place = sessionPlace(s, repo);
      const name = place === null ? null : place.kind === "worktree" ? place.name : place.branch;
      return name === branch.name;
    });
    const claude = path !== null && chats.some((c) => c.cwd === path);
    if (nest.length === 0 && !claude) continue;
    const dots = nest.map((s) => chatOf(tone(s)));
    found.set(
      branch.name,
      dots.reduce<BranchChat>((a, b) => (URGENCY[b] > URGENCY[a] ? b : a), "idle"),
    );
  }
  return found;
}
