// App paths, so notifications can open an item and a reload lands where the user was:
// /inbox, /projects, /account, /chat/<session id> and /pixie/<pixie id>.

export type Tab = "inbox" | "projects" | "account";

export interface Route {
  tab: Tab;
  // The session open full screen, if any.
  chat: string | null;
  // Or the pixie whose page is open (D057).
  pixie?: string;
}

const TABS: readonly string[] = ["inbox", "projects", "account"];

export function parseRoute(path: string): Route {
  const [, first = "", second, ...rest] = path.split("/");
  if ((first === "chat" || first === "pixie") && second && rest.length === 0) {
    try {
      const id = decodeURIComponent(second);
      // A chat or a pixie opens over the projects tab, where going back makes sense.
      return first === "chat"
        ? { tab: "projects", chat: id }
        : { tab: "projects", chat: null, pixie: id };
    } catch {
      return { tab: "inbox", chat: null };
    }
  }
  return {
    tab: TABS.includes(first) && second === undefined ? (first as Tab) : "inbox",
    chat: null,
  };
}

export function routePath({ tab, chat, pixie }: Route): string {
  if (pixie !== undefined) return `/pixie/${encodeURIComponent(pixie)}`;
  return chat === null ? `/${tab}` : `/chat/${encodeURIComponent(chat)}`;
}
