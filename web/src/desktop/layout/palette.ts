// The Ctrl K palette, ported from NestKit's CommandPalette.swift: chats of every open
// project, the current project's commands and the other projects, filtered by every word
// of the query, then the messages the daemon's search found, with a keyboard selection.
import type { Editors } from "../../api/types.ts";
import { GENERAL } from "../../store/general.ts";
import type { ProjectView } from "./project.ts";

export type PaletteAction =
  | { openChat: string; project: string }
  | { newChat: true }
  | { newTerminal: true }
  | { newBrowser: true }
  | { showView: ProjectView }
  | { toggleSidebar: true }
  | { toggleActivity: true }
  | { showUsage: true }
  | { openInEditor: true }
  | { goToProject: string }
  | { openMessage: string; project: string; event: number | null };

export type PaletteGroup = "Chats" | "Commands" | "Projects" | "Messages";

export interface PaletteItem {
  group: PaletteGroup;
  title: string;
  subtitle: string;
  action: PaletteAction;
}

// Search hits come from this many characters on, as the Mac's MessageSearch.
export const MESSAGE_SEARCH_MINIMUM = 2;

export interface Palette {
  items: PaletteItem[];
  query: string;
  // Index into `visible`.
  selection: number;
  messages: PaletteItem[];
}

export function palette(items: PaletteItem[]): Palette {
  return { items, query: "", selection: 0, messages: [] };
}

export function searchesMessages(p: Palette): boolean {
  return p.query.trim().length >= MESSAGE_SEARCH_MINIMUM;
}

export function visible(p: Palette): PaletteItem[] {
  const words = p.query.toLowerCase().split(" ").filter(Boolean);
  if (words.length === 0) return p.items;
  const matches = p.items.filter((item) => {
    const text = `${item.title} ${item.subtitle}`.toLowerCase();
    return words.every((word) => text.includes(word));
  });
  return [...matches, ...p.messages];
}

/** Shown items in runs of one group, each with the index of its first item. */
export function sections(
  items: PaletteItem[],
): { group: string; start: number; items: PaletteItem[] }[] {
  const out: { group: string; start: number; items: PaletteItem[] }[] = [];
  items.forEach((item, index) => {
    const last = out.at(-1);
    if (last?.group === item.group) last.items.push(item);
    else out.push({ group: item.group, start: index, items: [item] });
  });
  return out;
}

export function selected(p: Palette): PaletteItem | null {
  return visible(p)[p.selection] ?? null;
}

/** A new query selects the first match again; one too short to search drops the hits. */
export function search(p: Palette, query: string): Palette {
  const next = { ...p, query, selection: 0 };
  return searchesMessages(next) ? next : { ...next, messages: [] };
}

/** The daemon's hits for `query`, once per pane and event; ignored when the query changed. */
export function showMessages(p: Palette, query: string, hits: PaletteItem[]): Palette {
  if (query !== p.query || !searchesMessages(p)) return p;
  const seen = new Set<string>();
  const messages = hits.filter((hit) => {
    const key = JSON.stringify(hit.action);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const next = { ...p, messages };
  return { ...next, selection: Math.min(p.selection, Math.max(visible(next).length - 1, 0)) };
}

/** Arrow keys: moves the selection, wrapping at both ends. */
export function move(p: Palette, step: number): Palette {
  const count = visible(p).length;
  if (count === 0) return p;
  return { ...p, selection: (((p.selection + step) % count) + count) % count };
}

export interface CatalogChat {
  id: string;
  title: string;
  project: string;
  status: string;
}

export interface CatalogInput {
  open: string[];
  current: string | null;
  chats: CatalogChat[];
  view: ProjectView;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  // The default editor's name, while one is installed (B152).
  editor: string | null;
  // How many items need the user in a project.
  attention: (project: string) => number;
}

/** The default editor's name, or null while none is installed or listed. */
export function defaultEditorName(editors: Editors | null): string | null {
  return editors?.installed.find((editor) => editor.id === editors.default)?.name ?? null;
}

/** The entries for the window: open projects' chats, the project's commands, the others. */
export function catalog(input: CatalogInput): PaletteItem[] {
  const items: PaletteItem[] = input.chats
    .filter((chat) => input.open.includes(chat.project))
    .map((chat) => ({
      group: "Chats",
      title: chat.title,
      subtitle: `${chat.project} · ${chat.status}`,
      action: { openChat: chat.id, project: chat.project },
    }));
  const project = input.current;
  if (project !== null) {
    const offerBoard = input.view === "workspace";
    const command = (title: string, subtitle: string, action: PaletteAction): PaletteItem => ({
      group: "Commands",
      title,
      subtitle,
      action,
    });
    items.push(
      command(`New chat in ${project}`, "Chat", { newChat: true }),
      // General's folder belongs to Nest: no terminal there, as in its project menu.
      ...(project === GENERAL
        ? []
        : [command(`New terminal in ${project}`, "Terminal", { newTerminal: true })]),
      command("New browser", "Browser", { newBrowser: true }),
      command(offerBoard ? "Show the Board view" : "Show the Workspace view", "View", {
        showView: offerBoard ? "board" : "workspace",
      }),
    );
    if (input.view !== "artifacts") {
      items.push(command("Show the Artifacts view", "View", { showView: "artifacts" }));
    }
    items.push(
      command(`${input.leftCollapsed ? "Expand" : "Collapse"} the chat sidebar`, "Layout", {
        toggleSidebar: true,
      }),
      command(`${input.rightCollapsed ? "Expand" : "Collapse"} the activity panel`, "Layout", {
        toggleActivity: true,
      }),
      command("Show usage", "Usage", { showUsage: true }),
    );
    if (input.editor !== null) {
      items.push(command(`Open ${project} in ${input.editor}`, "Project", { openInEditor: true }));
    }
  }
  for (const other of input.open) {
    if (other === project) continue;
    const attention = input.attention(other);
    items.push({
      group: "Projects",
      title: `Go to ${other}`,
      subtitle: attention > 0 ? `${String(attention)} need you` : "Project",
      action: { goToProject: other },
    });
  }
  return items;
}
