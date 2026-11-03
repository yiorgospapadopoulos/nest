import { createContext, use } from "react";
import type { RepoApp } from "../../api/client.ts";
import type { CreatePixieBody, RepoConfig } from "../../api/types.ts";
import type { ProjectState, ProjectView } from "../layout/project.ts";
import type { DropSide } from "../layout/workspace.ts";
import type { SettingsPlace, SettingsTarget } from "../settings/catalog.ts";
import type { Desk } from "./desk.ts";

/** The window's controller, as the Mac's Shell: what every part of the window acts through. */
export interface Shell {
  desk: Desk;
  // The project shown, or null in the Pixies tab.
  project: string | null;
  repo: RepoConfig;
  // The shown tab's workspace: the project's, or the Pixies tab's.
  state: ProjectState;
  // Changes the shown tab's state.
  update: (change: (state: ProjectState) => void) => void;
  workspaceSize: () => { width: number; height: number };
  setWorkspaceSize: (size: { width: number; height: number }) => void;

  selectTab: (name: string) => void;
  openProject: (name: string) => void;
  closeTab: (name: string) => void;
  // Moves a tab and saves the new project order for every device (D090).
  moveTab: (name: string, index: number) => void;
  // Opens the shown project's folder in VS Code, the file manager or a terminal.
  openIn: (app: RepoApp) => void;

  openPane: (pane: string) => void;
  openChat: (id: string, event?: number) => void;
  // Shows `next` in place of the draft or chat pane `pane`.
  replacePane: (pane: string, next: string) => void;
  dropPane: (pane: string, target: string | null, side: DropSide) => void;
  closePane: (pane: string) => void;
  newChat: () => void;
  newTerminal: () => void;
  newBrowser: (url?: string) => void;
  openPixie: (id: string) => void;
  // A habit run's chat, read-only in a sheet over the window (the Mac's HabitRunSheet).
  openHabitRun: (session: string) => void;
  // What a subagent, pixie or team did in a chat, read-only in a sheet (the Mac's WorkSheet).
  openWork: (target: WorkTarget) => void;
  sheet: ShellSheet | null;
  closeSheet: () => void;
  // Opens a project's activity panel on Needs you, as for an approval to answer.
  showNeedsYou: (project: string) => void;
  focusEvent: (pane: string) => number | undefined;

  // The Pixies tab's right panel shows the focused pixie's details (PixiesView.swift).
  pixieDetailsOpen: boolean;
  // A pixie pane's Details button: shows that pixie's details, or hides them if shown.
  togglePixieDetails: (id: string) => void;
  showPixieDetails: (id: string) => void;
  setPixieDetailsOpen: (open: boolean) => void;
  // Creates a pixie and opens its pane; with `details`, its details too, to set it up.
  createPixie: (body: CreatePixieBody, details: boolean) => void;
  // The Pixies list shows hidden pixies too.
  showsHiddenPixies: boolean;
  setShowsHiddenPixies: (shown: boolean) => void;

  setView: (view: ProjectView) => void;
  toggleSidebar: () => void;
  toggleActivity: () => void;
  setSidebarWidth: (width: number) => void;

  // The Settings page while Settings shows in the window, in place of the tab's content.
  settings: SettingsPlace | null;
  // Opens Settings on a page or a project's page; General when neither is given.
  openSettings: (target?: SettingsTarget) => void;
  closeSettings: () => void;
  palette: boolean;
  setPalette: (open: boolean) => void;
  // The search the palette opens with (searchPalette), else empty.
  paletteSearch: string;
  // Opens the palette with `text` in its search, as the Mac's searchPalette for /resume.
  searchPalette: (text: string) => void;
}

/** Whose work in a chat the work sheet shows. */
export type WorkTarget =
  | { subagent: { session: string; tool: string } }
  | { pixie: { session: string; pixie: string } }
  | { team: { session: string; team: string; members: string[] } };

export type ShellSheet = { habitRun: string } | { work: WorkTarget };

export const ShellContext = createContext<Shell | null>(null);

export function useShell(): Shell {
  const shell = use(ShellContext);
  if (shell === null) throw new Error("useShell outside the desktop shell");
  return shell;
}
