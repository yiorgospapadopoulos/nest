// The window's arrangement, kept on this device: the tabs, each project's workspace with
// its tool panes and side panels, the Pixies tab's workspace and the sidebar's width.
import { ProjectState, type ProjectView, type RightCard } from "../layout/project.ts";
import { SIDEBAR_STANDARD, storedSidebar } from "../layout/sidebar.ts";
import { NO_TABS, type Tabs } from "../layout/tabs.ts";
import type { ToolPane } from "../layout/tools.ts";
import { WorkspaceLayout, type WorkspaceData } from "../layout/workspace.ts";
import { isDraft } from "./panes.ts";

export interface Desk {
  tabs: Tabs;
  projects: Record<string, ProjectState>;
  pixies: ProjectState;
  sidebarWidth: number;
}

export const EMPTY_DESK: Desk = {
  tabs: NO_TABS,
  projects: {},
  pixies: new ProjectState(),
  sidebarWidth: SIDEBAR_STANDARD,
};

export const DESK_KEY = "nest.desktop.desk";

interface SavedProject {
  layout: WorkspaceData;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  openCards: RightCard[];
  view: ProjectView;
  selectedChat: string | null;
  tools: ToolPane[];
}

interface SavedDesk {
  tabs: Tabs;
  projects: Record<string, SavedProject>;
  pixies: SavedProject;
  sidebarWidth: number;
}

// A new chat's draft lives only while the window shows it, as on the Mac.
function saveProject(shown: ProjectState): SavedProject {
  const state = shown.copy();
  for (const pane of state.layout.leaves.filter(isDraft)) state.closePane(pane);
  return {
    layout: state.layout.toJSON(),
    leftCollapsed: state.leftCollapsed,
    rightCollapsed: state.rightCollapsed,
    openCards: [...state.openCards],
    view: state.view,
    selectedChat: state.selectedChat,
    tools: state.openTools,
  };
}

function loadProject(saved: SavedProject): ProjectState {
  const state = new ProjectState();
  state.layout = WorkspaceLayout.from(saved.layout);
  state.leftCollapsed = saved.leftCollapsed;
  state.rightCollapsed = saved.rightCollapsed;
  state.openCards = new Set(saved.openCards);
  state.view = saved.view;
  state.selectedChat = saved.selectedChat;
  state.tools = new Map(saved.tools.map((tool) => [tool.id, tool]));
  // Arrangements saved before drafts were left out.
  for (const pane of state.layout.leaves.filter(isDraft)) state.closePane(pane);
  return state;
}

export function saveDesk(storage: Storage, desk: Desk): void {
  const saved: SavedDesk = {
    tabs: desk.tabs,
    projects: Object.fromEntries(
      Object.entries(desk.projects).map(([name, state]) => [name, saveProject(state)]),
    ),
    pixies: saveProject(desk.pixies),
    sidebarWidth: desk.sidebarWidth,
  };
  try {
    storage.setItem(DESK_KEY, JSON.stringify(saved));
  } catch {
    // A full or blocked storage only loses the arrangement for the next start.
  }
}

/** The saved arrangement; an empty one when there is none or it cannot be read. */
export function loadDesk(storage: Storage): Desk {
  try {
    const text = storage.getItem(DESK_KEY);
    if (text === null) return EMPTY_DESK;
    const saved = JSON.parse(text) as SavedDesk;
    return {
      tabs: saved.tabs,
      projects: Object.fromEntries(
        Object.entries(saved.projects).map(([name, state]) => [name, loadProject(state)]),
      ),
      pixies: loadProject(saved.pixies),
      sidebarWidth: storedSidebar(String(saved.sidebarWidth)),
    };
  } catch {
    return EMPTY_DESK;
  }
}
