// What a desktop menu lists, as the Mac's menus: items with a checkmark column and an
// optional grey line under the title, section titles, separators, plain notes and
// submenus. Pure, so the keyboard rules are tested without a DOM.
import type { MenuIconName } from "./menuIcons.tsx";

export interface MenuItem {
  type?: "item";
  title: string;
  // A second line in grey, as OptionItem's description.
  detail?: string;
  checked?: boolean;
  disabled?: boolean;
  // The detail in the wait colour.
  warns?: boolean;
  // A destructive action, in red.
  danger?: boolean;
  // Such as "Ctrl+W", on the right.
  shortcut?: string;
  // The symbol beside the title, where the Mac's item is a Label with one.
  icon?: MenuIconName;
  onSelect: () => void;
}

export interface MenuSubmenu {
  type: "submenu";
  title: string;
  disabled?: boolean;
  icon?: MenuIconName;
  items: MenuEntry[];
}

export type MenuEntry =
  | MenuItem
  | MenuSubmenu
  | { type: "separator" }
  // A grey title over the items after it, as SwiftUI's Section("...").
  | { type: "section"; title: string }
  // A grey line that is not a choice, as a menu's Text("...").
  | { type: "note"; text: string };

export const separator: MenuEntry = { type: "separator" };

/** Whether the entry can be highlighted and chosen. */
export function isActionable(entry: MenuEntry): entry is MenuItem | MenuSubmenu {
  if (entry.type !== undefined && entry.type !== "item" && entry.type !== "submenu") return false;
  return entry.disabled !== true;
}

/**
 * The next highlighted entry from `from` moving by `delta` (1 down, -1 up), wrapping as
 * AppKit's menus do; from nothing (-1) down is the first and up the last. -1 when there
 * is none.
 */
export function step(entries: MenuEntry[], from: number, delta: 1 | -1): number {
  const count = entries.length;
  if (count === 0) return -1;
  let index = from === -1 ? (delta === 1 ? -1 : count) : from;
  for (let tries = 0; tries < count; tries++) {
    index = (index + delta + count) % count;
    const entry = entries[index];
    if (entry !== undefined && isActionable(entry)) return index;
  }
  return -1;
}

export function first(entries: MenuEntry[]): number {
  return step(entries, -1, 1);
}

export function last(entries: MenuEntry[]): number {
  return step(entries, -1, -1);
}

/** Typing letters highlights the next entry whose title starts with them, after `from`. */
export function typeahead(entries: MenuEntry[], from: number, typed: string): number {
  const text = typed.toLowerCase();
  const count = entries.length;
  for (let offset = 1; offset <= count; offset++) {
    // A first letter moves on from the current entry; more letters may keep it.
    const index = (from + (typed.length > 1 ? offset - 1 : offset) + count) % count;
    const entry = entries[index];
    if (entry !== undefined && isActionable(entry)) {
      if (entry.title.toLowerCase().startsWith(text)) return index;
    }
  }
  return from;
}
