import type { RepoConfig, RepoPatch, WorktreeConfig } from "../../../api/types.ts";

// A project's worktree settings and their words, as NestKit's WorktreeConfig, RepoPatch,
// SetupTimeout and ProjectRemoval.

/**
 * The links with `text` added, trimmed; null when it is blank, already there, or not a
 * relative path inside the project (the daemon refuses those).
 */
export function addLink(link: readonly string[], text: string): string[] | null {
  const path = text.trim();
  const parts = path.split("/").filter((part) => part !== "");
  if (path.startsWith("/") || parts.every((part) => part === ".") || parts.includes("..")) {
    return null;
  }
  return link.includes(path) ? null : [...link, path];
}

/** The links without `path`; one already gone is left alone. */
export function removeLink(link: readonly string[], path: string): string[] {
  return link.filter((item) => item !== path);
}

/** The commands with `text` added, trimmed; null when it is blank. */
export function addSetup(setup: readonly string[], text: string): string[] | null {
  const command = text.trim();
  return command === "" ? null : [...setup, command];
}

/** Removes the command shown at `index`, if it is still the one there. */
export function removeSetup(setup: readonly string[], command: string, index: number): string[] {
  return setup[index] === command ? setup.filter((_, at) => at !== index) : [...setup];
}

const SETUP_TIMEOUTS = [300, 900, 1800];

/** The setup time limit's choices in seconds, with a value set elsewhere kept. */
export function setupTimeoutChoices(value: number): number[] {
  return SETUP_TIMEOUTS.includes(value)
    ? SETUP_TIMEOUTS
    : [...SETUP_TIMEOUTS, value].sort((a, b) => a - b);
}

/** "15 minutes", "90 seconds", "1 minute". */
export function setupTimeoutLabel(seconds: number): string {
  if (seconds % 60 !== 0) return `${String(seconds)} seconds`;
  const minutes = seconds / 60;
  return minutes === 1 ? "1 minute" : `${String(minutes)} minutes`;
}

/** What removing the project from Nest does, for its confirmation. */
export function removalConsequence(chats: number): string {
  const folder = "Nest forgets this project. Its folder stays as it is.";
  if (chats === 0) return folder;
  return chats === 1
    ? `${folder} Its chat is deleted for good, with its worktree and history; its branch stays.`
    : `${folder} Its ${String(chats)} chats are deleted for good, with their worktrees and history; their branches stay.`;
}

const same = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((item, index) => item === b[index]);

/** Only the worktree settings that differ, so a change cannot undo another made meanwhile. */
export function worktreePatch(old: WorktreeConfig, next: WorktreeConfig): RepoPatch {
  return {
    ...(old.default === next.default ? {} : { default: next.default }),
    ...(same(old.link, next.link) ? {} : { link: next.link }),
    ...(same(old.setup, next.setup) ? {} : { setup: next.setup }),
  };
}

export type ProjectIcon = Pick<RepoConfig, "icon" | "icon_color">;

/** Only the parts of the icon that differ. */
export function iconPatch(old: ProjectIcon, next: ProjectIcon): RepoPatch {
  return {
    ...(old.icon === next.icon ? {} : { icon: next.icon }),
    ...(old.icon_color === next.icon_color ? {} : { icon_color: next.icon_color }),
  };
}
