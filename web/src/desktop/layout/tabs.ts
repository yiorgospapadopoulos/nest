// The tab strip's project tabs, ported from NestKit's AppStore (open, select, close, move)
// and TabReorder.swift (dragging a tab along the strip).
import { GENERAL } from "../../store/general.ts";

export interface Tabs {
  // Open project tabs by repo name, General first, then in the repos' order.
  open: string[];
  // The project shown, or null while the Pixies tab is.
  current: string | null;
  // The project shown when the Pixies tab was chosen, to go back to.
  last: string | null;
}

export const NO_TABS: Tabs = { open: [], current: null, last: null };

/** The tab the window shows: a project's name, or "pixies". */
export function shownTab(tabs: Tabs): string {
  return tabs.current ?? "pixies";
}

function sorted(open: string[], repos: string[]): string[] {
  const rank = (name: string) => {
    if (name === GENERAL) return -1;
    const index = repos.indexOf(name);
    return index === -1 ? Number.MAX_SAFE_INTEGER : index;
  };
  return open
    .map((name, offset) => ({ name, offset }))
    .sort((a, b) => rank(a.name) - rank(b.name) || a.offset - b.offset)
    .map((tab) => tab.name);
}

/**
 * After the repos load: tabs of repos that are gone close, the first repo (General
 * without one) opens when no tab is open, and the tabs follow the repos' order. The
 * Pixies tab stays chosen.
 */
export function withRepos(tabs: Tabs, repos: string[]): Tabs {
  const names = new Set([...repos, GENERAL]);
  let open = tabs.open.filter((name) => names.has(name));
  if (open.length === 0) open = [repos[0] ?? GENERAL];
  open = sorted(open, repos);
  const keep = (name: string | null) => (name !== null && open.includes(name) ? name : null);
  if (tabs.current === null && tabs.open.length > 0) {
    return { open, current: null, last: keep(tabs.last) ?? open[0] ?? null };
  }
  const current = keep(tabs.current) ?? open[0] ?? null;
  return { open, current, last: current };
}

export function openProject(tabs: Tabs, name: string, repos: string[]): Tabs {
  const open = tabs.open.includes(name) ? tabs.open : sorted([...tabs.open, name], repos);
  return { open, current: name, last: name };
}

export function selectProject(tabs: Tabs, name: string): Tabs {
  return tabs.open.includes(name) ? { ...tabs, current: name, last: name } : tabs;
}

export function selectPixies(tabs: Tabs): Tabs {
  return { ...tabs, current: null, last: tabs.current ?? tabs.last };
}

/** Closes a tab; the last project tab stays open. */
export function closeProject(tabs: Tabs, name: string): Tabs {
  const index = tabs.open.indexOf(name);
  if (tabs.open.length <= 1 || index === -1) return tabs;
  const open = tabs.open.filter((n) => n !== name);
  const neighbour = open[Math.max(0, index - 1)] ?? null;
  const current = tabs.current === name ? neighbour : tabs.current;
  const last = tabs.last === name ? neighbour : tabs.last;
  return { open, current, last };
}

/** Ctrl 1 to 9: the tab at a position; 9 is always the last tab. */
export function selectProjectAt(tabs: Tabs, index: number): Tabs {
  if (tabs.open.length === 0 || index < 0) return tabs;
  const name = index >= 8 ? tabs.open.at(-1) : tabs.open[index];
  return name === undefined ? tabs : selectProject(tabs, name);
}

/** The next (or, with a negative step, previous) project tab, wrapping around. */
export function selectProjectOffset(tabs: Tabs, offset: number): Tabs {
  const from = tabs.current ?? tabs.last;
  const index = from === null ? -1 : tabs.open.indexOf(from);
  if (index === -1) return tabs;
  const count = tabs.open.length;
  const name = tabs.open[(((index + offset) % count) + count) % count];
  return name === undefined ? tabs : selectProject(tabs, name);
}

/** Moves a tab to `index` among the open tabs on this device; General stays first. */
export function moveProject(tabs: Tabs, name: string, index: number): Tabs {
  const from = tabs.open.indexOf(name);
  if (name === GENERAL || from === -1) return tabs;
  const first = tabs.open.includes(GENERAL) ? 1 : 0;
  const target = Math.min(Math.max(index, first), tabs.open.length - 1);
  if (target === from) return tabs;
  const open = tabs.open.filter((n) => n !== name);
  open.splice(target, 0, name);
  return { ...tabs, open };
}

/**
 * The project order every device shows (D090) after a tab moved, as the Mac's moveProject:
 * the project goes just before the open tab that now follows it, or just after the one
 * before it when it is last. Null when nothing moved or the repos have not loaded.
 */
export function repoOrderAfterMove(repos: string[], before: Tabs, after: Tabs, name: string) {
  const index = after.open.indexOf(name);
  if (index === -1 || before.open.indexOf(name) === index) return null;
  const order = repos.filter((n) => n !== name);
  const next = after.open[index + 1];
  const [neighbour, offset] = next !== undefined ? [next, 0] : [after.open[index - 1], 1];
  const at = neighbour === undefined ? -1 : order.indexOf(neighbour);
  if (at === -1) return null;
  order.splice(at + offset, 0, name);
  return order;
}

/**
 * The project order to save once a project was added (D090), or null. The list shows a new
 * project last, while the daemon lists projects its saved order leaves out by file name,
 * so after a restart they moved; saving the whole order keeps them where they were.
 */
export function orderAfterAdding(before: string[], after: string[]): string[] | null {
  if (before.length === 0) return null;
  return after.some((name) => !before.includes(name)) ? after : null;
}

/** The position a tab dragged from `start` by `translation` lands at, by whole steps. */
export function reorderTarget(
  start: number,
  translation: number,
  step: number,
  count: number,
): number {
  if (step <= 0 || count <= 0) return start;
  const ratio = translation / step;
  // Halves round away from zero, as Swift does.
  const moved = Math.sign(ratio) * Math.round(Math.abs(ratio));
  return Math.min(Math.max(start + moved, 0), count - 1);
}

/** How far the tab at `index` slides aside while the tab from `start` is over `target`. */
export function reorderOffset(index: number, start: number, target: number, step: number): number {
  if (target > start && index > start && index <= target) return -step;
  if (target < start && index >= target && index < start) return step;
  return 0;
}
