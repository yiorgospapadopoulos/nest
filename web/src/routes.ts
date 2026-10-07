// App paths, so notifications can open an item and a reload lands where the user was:
// /inbox, /projects, /account and /chat/<session id>.

export type Tab = "inbox" | "projects" | "account";

export interface Route {
  tab: Tab;
  // The session open full screen, if any.
  chat: string | null;
}

const TABS: readonly string[] = ["inbox", "projects", "account"];

export function parseRoute(path: string): Route {
  const [, first = "", second, ...rest] = path.split("/");
  if (first === "chat" && second && rest.length === 0) {
    try {
      // A chat opens over the projects tab, where going back makes sense.
      return { tab: "projects", chat: decodeURIComponent(second) };
    } catch {
      return { tab: "inbox", chat: null };
    }
  }
  return {
    tab: TABS.includes(first) && second === undefined ? (first as Tab) : "inbox",
    chat: null,
  };
}

export function routePath({ tab, chat }: Route): string {
  return chat === null ? `/${tab}` : `/chat/${encodeURIComponent(chat)}`;
}
