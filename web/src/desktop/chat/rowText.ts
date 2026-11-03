// How transcript rows fold long content, ported from NestKit's CollapsedOutput and
// EditDiff: whole when short, else the first lines and "Show N more lines". Nothing is cut
// for good (B59).
import type { DiffLine } from "../../transcript/edits.ts";

export const OUTPUT_LINES = 10;
export const OUTPUT_CHARACTERS = 2000;
export const DIFF_LINES = 8;

export interface Collapsed {
  preview: string;
  // "Show 20 more lines", "Show all" when only long lines are hidden; null when whole.
  more: string | null;
}

const moreLines = (n: number) => `Show ${String(n)} more line${n === 1 ? "" : "s"}`;

export function collapsedOutput(text: string): Collapsed {
  let breaks = 0;
  let cut = -1;
  for (let at = text.indexOf("\n"); at !== -1; at = text.indexOf("\n", at + 1)) {
    breaks += 1;
    if (breaks === OUTPUT_LINES) cut = at;
  }
  const head = cut === -1 ? text : text.slice(0, cut);
  const hidden = cut === -1 ? 0 : breaks + 1 - OUTPUT_LINES;
  const preview = head.length > OUTPUT_CHARACTERS ? head.slice(0, OUTPUT_CHARACTERS) : head;
  if (preview.length >= text.length) return { preview: text, more: null };
  return { preview, more: hidden > 0 ? moreLines(hidden) : "Show all" };
}

/** An edit's hunks (split at its gaps), all of them or the first lines while collapsed. */
export function diffHunks(
  lines: DiffLine[],
  expanded: boolean,
): { hunks: DiffLine[][]; more: string | null } {
  const hunks: DiffLine[][] = [[]];
  for (const line of lines) {
    if (line.kind === "gap") hunks.push([]);
    else hunks.at(-1)?.push(line);
  }
  const all = hunks.filter((h) => h.length > 0);
  const count = all.reduce((sum, h) => sum + h.length, 0);
  const hidden = Math.max(count - DIFF_LINES, 0);
  if (expanded || hidden === 0)
    return { hunks: all, more: hidden === 0 ? null : moreLines(hidden) };
  const shown: DiffLine[][] = [];
  let left = DIFF_LINES;
  for (const hunk of all) {
    if (left <= 0) break;
    shown.push(hunk.slice(0, left));
    left -= Math.min(hunk.length, left);
  }
  return { hunks: shown, more: moreLines(hidden) };
}

/** The latest line of streamed text, as a collapsed subagent's preview. */
export function latestLine(text: string): string | null {
  const lines = text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
  return lines.at(-1) ?? null;
}
