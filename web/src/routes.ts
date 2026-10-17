// App paths, so notifications can open an item and a reload lands where the user was:
// /inbox, /projects, /settings, /settings/<page>, /settings/projects/<project>,
// /settings/agents/usage (the usage breakdown, B84),
// /chat/<session id> and /pixie/<pixie id>. /account, the Settings tab's old name, still
// opens Settings (B81).

export type Tab = "inbox" | "projects" | "settings";

// The Settings pages, in the order the list shows them (B81).
export const SETTINGS_PAGES = [
  "general",
  "appearance",
  "notifications",
  "agents",
  "pixies",
  "accounts",
  "extensions",
  "devices",
] as const;

export type SettingsPageId = (typeof SETTINGS_PAGES)[number];

// A Settings page, a project's page in Settings, or the usage breakdown under Agents.
export type SettingsPage = { page: SettingsPageId } | { project: string } | { detail: "usage" };

export interface Route {
  tab: Tab;
  // The session open full screen, if any.
  chat: string | null;
  // Or the pixie whose page is open (D072).
  pixie?: string;
  // The Settings page open, on the Settings tab.
  settings?: SettingsPage;
}

const TABS: readonly string[] = ["inbox", "projects", "settings"];
const INBOX: Route = { tab: "inbox", chat: null };

function decoded(part: string): string | null {
  try {
    return decodeURIComponent(part);
  } catch {
    return null;
  }
}

function settingsRoute(rest: string[]): Route {
  const [first, second, ...more] = rest;
  if (first === undefined) return { tab: "settings", chat: null };
  if (first === "projects" && second !== undefined && second !== "" && more.length === 0) {
    const project = decoded(second);
    return project === null ? INBOX : { tab: "settings", chat: null, settings: { project } };
  }
  if (first === "agents" && second === "usage" && more.length === 0) {
    return { tab: "settings", chat: null, settings: { detail: "usage" } };
  }
  const page = SETTINGS_PAGES.find((id) => id === first);
  return page !== undefined && second === undefined
    ? { tab: "settings", chat: null, settings: { page } }
    : INBOX;
}

export function parseRoute(path: string): Route {
  const [, first = "", second, ...rest] = path.split("/");
  if ((first === "chat" || first === "pixie") && second && rest.length === 0) {
    const id = decoded(second);
    if (id === null) return INBOX;
    // A chat or a pixie opens over the projects tab, where going back makes sense.
    return first === "chat"
      ? { tab: "projects", chat: id }
      : { tab: "projects", chat: null, pixie: id };
  }
  if (first === "settings") return settingsRoute(second === undefined ? [] : [second, ...rest]);
  if (first === "account" && second === undefined) return { tab: "settings", chat: null };
  return {
    tab: TABS.includes(first) && second === undefined ? (first as Tab) : "inbox",
    chat: null,
  };
}

export function routePath({ tab, chat, pixie, settings }: Route): string {
  if (pixie !== undefined) return `/pixie/${encodeURIComponent(pixie)}`;
  if (chat !== null) return `/chat/${encodeURIComponent(chat)}`;
  if (tab === "settings" && settings !== undefined) {
    if ("detail" in settings) return "/settings/agents/usage";
    return "page" in settings
      ? `/settings/${settings.page}`
      : `/settings/projects/${encodeURIComponent(settings.project)}`;
  }
  return `/${tab}`;
}
