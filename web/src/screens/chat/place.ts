import type { ClaudeChat, RepoConfig, Session } from "../../api/types.ts";

/**
 * Where a chat works, as its list row and header say it (B55, as the Mac's ChatPlace): a
 * worktree, named by its branch (the two are one pair), or the project folder, on the
 * branch checked out there now, which every in-place chat shares.
 */
export type ChatPlace =
  // `folder` is null while the worktree is still being made.
  | { kind: "worktree"; name: string; folder: string | null }
  // `branch` is null when the folder's branch is unknown or its checkout detached.
  | { kind: "checkout"; folder: string; branch: string | null };

/** A Nest chat's place; null in a plain folder or when an in-place chat's folder is unknown. */
export function sessionPlace(session: Session, repo: RepoConfig | undefined): ChatPlace | null {
  if (repo?.git === false) return null;
  if (session.mode === "worktree" || session.worktree_path !== null) {
    return {
      kind: "worktree",
      name: session.branch ?? "New worktree",
      folder: session.worktree_path,
    };
  }
  const folder = session.cwd ?? repo?.path;
  return folder === undefined ? null : checkout(folder, repo);
}

/** A Claude Code chat's place: the worktree Claude Code made, else the folder. */
export function claudeChatPlace(chat: ClaudeChat, repo: RepoConfig | undefined): ChatPlace | null {
  if (repo?.git === false) return null;
  return chat.worktree === null
    ? checkout(chat.cwd, repo)
    : { kind: "worktree", name: chat.worktree, folder: chat.cwd };
}

function checkout(folder: string, repo: RepoConfig | undefined): ChatPlace {
  return { kind: "checkout", folder, branch: repo?.current_branch ?? null };
}

/** The place's shown name: the worktree's, or the folder's branch. */
export function placeName(place: ChatPlace): string {
  return place.kind === "worktree" ? place.name : (place.branch ?? "This folder");
}

/** The end of a list row's accessible name, as ", on main"; nothing without a place. */
export function placeLabel(place: ChatPlace | null): string {
  if (place === null) return "";
  if (place.kind === "worktree") return `, worktree ${place.name}`;
  return place.branch === null ? ", in this folder" : `, on ${place.branch}`;
}
