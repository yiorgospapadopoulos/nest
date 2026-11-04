import type { EarlierWorktree, Session } from "../../api/types.ts";

// The end of a name that stays when it is shortened in the middle.
const TAIL = 10;

/** The worktrees a chat worked in before, oldest first (B119). */
export const earlierOf = (session: Session) => session.earlier_worktrees ?? [];

/** Its branch, or its folder's name without one. */
export const earlierName = (worktree: EarlierWorktree) =>
  worktree.branch ?? worktree.path.split("/").pop() ?? worktree.path;

/** A name's start, which CSS shortens with an ellipsis, and its end, which stays. */
export const nameEnds = (name: string): [string, string] => [
  name.slice(0, -TAIL),
  name.slice(-TAIL),
];
