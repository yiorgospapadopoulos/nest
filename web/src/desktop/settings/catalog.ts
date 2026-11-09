// The Settings pages and what their rows are called, for the sidebar's search, as NestKit's
// SettingsCatalog.swift (B81).
import { NOTIFY_TOGGLES } from "../notifications.ts";
import { SHORTCUT_GROUPS, SHORTCUTS } from "../layout/shortcuts.ts";

export const FIXED_PAGES = [
  "general",
  "appearance",
  "notifications",
  "agents",
  "computer",
  "usage",
  "performance",
  "storage",
  "pixies",
  "accounts",
  "devices",
  "shortcuts",
  "configuration",
  "features",
] as const;

export type FixedPage = (typeof FIXED_PAGES)[number];

/** A page of Settings: a fixed one, a project's, or Add project. */
export type SettingsPlace = { page: FixedPage | "addProject" } | { project: string };

/** What `openSettings` opens: a page, a project's page, or General when neither is given. */
export interface SettingsTarget {
  page?: FixedPage | "addProject";
  project?: string;
}

export function placeOf(target: SettingsTarget | undefined): SettingsPlace {
  if (target?.project !== undefined) return { project: target.project };
  return { page: target?.page ?? "general" };
}

export function samePlace(a: SettingsPlace, b: SettingsPlace): boolean {
  return "project" in a
    ? "project" in b && a.project === b.project
    : "page" in b && a.page === b.page;
}

const TITLES: Record<FixedPage | "addProject", string> = {
  general: "General",
  appearance: "Appearance",
  notifications: "Notifications",
  agents: "Agents",
  computer: "Computer use",
  usage: "Usage",
  performance: "Performance",
  storage: "Storage",
  pixies: "Pixies",
  accounts: "Accounts",
  devices: "Devices",
  shortcuts: "Keyboard shortcuts",
  configuration: "Configuration",
  features: "Features",
  addProject: "Add project",
};

export function placeTitle(place: SettingsPlace): string {
  return "project" in place ? place.project : TITLES[place.page];
}

const STUCK = ["Waiting on a prompt", "No new output", "Same call repeated", "One turn running"];
const USAGE_UNITS = ["Day", "Week", "Month", "Year"];
const WORKTREES = [
  "Worktrees folder",
  "Branch name prefix",
  "Check out submodules",
  "Remove merged worktrees",
];

const LABELS: Record<FixedPage | "addProject" | "project", readonly string[]> = {
  general: [
    "Sidebar",
    "Show automated chats",
    "Open in",
    "Default editor",
    "Linux",
    "Nest",
    "Version",
    "Restart Nest",
    "Voice input",
    "Model",
    "Setup",
    "Set up Nest",
    "Help",
    "Report a bug",
    "Uninstall",
    "Uninstall Nest",
  ],
  storage: [
    "Space used",
    "Used by Nest",
    "Attachments",
    "Artifacts",
    "Archive chats idle for",
    "Clean up",
    "Review large attachments",
    "Search index",
    "Rebuild",
  ],
  appearance: [
    "Mode",
    "Auto",
    "Light",
    "Dark",
    "Accent colour",
    "Chat background",
    "Image",
    "Visibility when empty",
    "Visibility with chats",
    "Grain",
    "Island settings",
    "Show the island",
    "Order",
    "Newest first",
    "Oldest first",
  ],
  notifications: [
    "Notify me about",
    "Delivery",
    "Sound",
    ...NOTIFY_TOGGLES.map((t) => t.title),
    "iPhone push",
    "ntfy",
    "Server",
    "Topic",
    "Link address",
  ],
  agents: [
    "New chats",
    "Model",
    "Thinking",
    "Permissions",
    "Work in",
    ...WORKTREES,
    "Stuck chats",
    ...STUCK,
  ],
  computer: [
    "Let chats use apps",
    "Permissions",
    "Accessibility for Nest Computer",
    "Screen Recording for Nest",
    "Pixies may use it",
    "Simulators and browser",
    "iOS Simulator",
    "Android Emulator",
    "Shared browser",
  ],
  usage: [
    "Limits",
    "5 hour",
    "Weekly",
    "Refresh",
    ...USAGE_UNITS,
    "Subagents",
    "Details",
    "Usage limits",
    "Check limits",
    "Warn me at",
    "Also as a notification",
  ],
  pixies: [
    "Your pixies",
    "Show hidden pixies",
    "Pixies and subagents can push",
    "New pixie",
    "New pixies start with",
    "Model",
    "Autonomy",
    "Project files",
    "Projects",
    "Chats running at once",
    "Chats started per day",
    "Habits",
    "Pause all habits",
    "Skip habit runs above",
    "Reports",
    "Send to the phone from",
  ],
  accounts: ["Claude", "Sign in", "Sign out", "GitHub", "Check again"],
  configuration: [
    "Shared",
    "Instructions",
    "AGENTS.md",
    "CLAUDE.md",
    "Skills",
    "New skill",
    "MCP servers",
    "Add server",
    "Engines",
    "Claude",
    "Codex",
    "Claude Code",
    "Install Claude Code",
    "Uses shared",
    "Copy to Shared",
    "Plugins",
    "Browse",
    "Marketplaces",
    "Connectors",
    "Hooks",
    "Subagents",
    "Slash commands",
    "Permission rules",
    "Settings file",
    "Rules",
    "config.toml",
  ],
  devices: ["Pair a device", "Revoke", "iPhone"],
  performance: [
    "Run all",
    "Clear old runs",
    "Context cost",
    "Turn speed and cache",
    "Load speed",
    "Waiting on you",
    "Activity",
    "Advanced",
    "What changed",
  ],
  // The groups' and features' names come from the daemon, through `listed`.
  features: ["New"],
  shortcuts: [
    ...SHORTCUT_GROUPS.map((g) => g.title),
    ...Object.values(SHORTCUTS).map((s) => s.title),
  ],
  project: [
    "General",
    "Name",
    "Folder",
    "Kind",
    "Default branch",
    "Push to",
    "Remove",
    "Chats",
    "Work in",
    "Worktrees",
    "Linked files",
    "Setup commands",
    "Setup time limit",
    ...WORKTREES,
    "Clean up",
    "Artifacts",
    "Look",
    "Tab icon",
    "Colour",
    "Chat background",
    "Configuration",
    "Instructions",
    "Project skills",
    "MCP servers",
    ".mcp.json",
  ],
  addProject: ["Folder", "Add"],
};

/** What the page's rows are called, for the search field. */
export function placeLabels(place: SettingsPlace): readonly string[] {
  return LABELS["project" in place ? "project" : place.page];
}

/**
 * Whether the page's title, one of its rows or one of the `extra` labels contains the
 * query, ignoring case and surrounding spaces; an empty query matches every page.
 */
export function matches(place: SettingsPlace, query: string, extra: readonly string[] = []) {
  const words = query.trim().toLowerCase();
  if (words === "") return true;
  return [placeTitle(place), ...placeLabels(place), ...extra].some((label) =>
    label.toLowerCase().includes(words),
  );
}

/**
 * The sidebar's pages: the fixed ones, then each project and Add project, as the query
 * leaves them. `features` are the Features page's group and feature names.
 */
export function listed(
  projects: readonly string[],
  query: string,
  features: readonly string[] = [],
): { pages: SettingsPlace[]; projects: SettingsPlace[] } {
  const fixed = FIXED_PAGES.map((page): SettingsPlace => ({ page }));
  const projectPages: SettingsPlace[] = [
    ...projects.map((project) => ({ project })),
    { page: "addProject" },
  ];
  return {
    pages: fixed.filter((place) =>
      matches(place, query, "page" in place && place.page === "features" ? features : []),
    ),
    projects: projectPages.filter((place) => matches(place, query)),
  };
}

// The tabs of a project's page; a plain folder has no worktrees or triggers.
export const PROJECT_TABS = [
  "General",
  "Configuration",
  "Chats",
  "Worktrees",
  "Triggers",
  "Look",
  "Artifacts",
] as const;

export type ProjectTab = (typeof PROJECT_TABS)[number];

export function projectTabs(git: boolean): ProjectTab[] {
  return PROJECT_TABS.filter((tab) => git || (tab !== "Worktrees" && tab !== "Triggers"));
}
