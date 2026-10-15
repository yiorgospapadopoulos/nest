import { useCallback, useEffect, useRef, useState } from "react";
import { NAVIGATE, type NavigateMessage } from "../pwa/navigate.ts";
import { parseRoute, routePath, type Route, type Tab } from "../routes.ts";
import { useStore } from "../store/context.ts";
import { needsCount } from "../store/selectors.ts";
import { Account } from "./account/Account.tsx";
import { ChatView, type ChatTarget } from "./chat/ChatView.tsx";
import type { PixieTab } from "./pixies/PixieView.tsx";
import { Inbox } from "./inbox/Inbox.tsx";
import { Projects } from "./projects/Projects.tsx";
import { TabBar } from "./TabBar.tsx";

/** The three tabs, with a chat pushed full screen over them; the address follows along. */
export function Shell() {
  const { state } = useStore();
  const [initial] = useState(() => parseRoute(window.location.pathname));
  const [tab, setTab] = useState<Tab>(initial.tab);
  const [project, setProject] = useState<string | null>(null);
  const [chat, setChat] = useState<ChatTarget | null>(() => routeTarget(initial));
  // The chosen project while it is still registered, else the first one.
  const current = state.repos.find((r) => r.name === project)?.name ?? state.repos[0]?.name ?? null;

  useEffect(() => {
    const path = routePath({
      tab,
      chat: chat !== null && "id" in chat ? chat.id : null,
      ...(chat !== null && "pixie" in chat ? { pixie: chat.pixie } : {}),
    });
    if (window.location.pathname !== path) window.history.replaceState(null, "", path);
  }, [tab, chat]);

  // What had focus when a chat opened over the tabs, to get it back when the chat closes.
  const opener = useRef<Element | null>(null);
  const showing = useRef(chat !== null);
  useEffect(() => {
    showing.current = chat !== null;
  }, [chat]);
  const show = useCallback((target: ChatTarget | null) => {
    if (target !== null && !showing.current) opener.current = document.activeElement;
    setChat(target);
  }, []);

  // A tapped notification sends an open app to its item (see the service worker).
  useEffect(() => {
    const worker = window.navigator.serviceWorker as ServiceWorkerContainer | undefined;
    if (worker === undefined) return;
    const go = (route: Route) => {
      setTab(route.tab);
      show(routeTarget(route));
    };
    const onMessage = (event: MessageEvent<NavigateMessage | null>) => {
      if (event.data?.type === NAVIGATE) go(parseRoute(event.data.url));
    };
    worker.addEventListener("message", onMessage);
    return () => {
      worker.removeEventListener("message", onMessage);
    };
  }, [show]);

  // The chat that just closed: once the tabs show again, focus goes back to what opened
  // it, such as an Inbox card or a search hit, or else to the chat's row (data-chat). A tap
  // leaves focus on the page itself, and an opener may be gone, as an answered card.
  // Holds the chat's id, or null for a new chat that was never sent (BUG-98).
  const closed = useRef<{ id: string | null } | null>(null);
  useEffect(() => {
    const last = closed.current;
    if (chat !== null || last === null) return;
    closed.current = null;
    const back = opener.current;
    opener.current = null;
    if (back instanceof HTMLElement && back !== document.body && back.isConnected) {
      back.focus();
      return;
    }
    const rows = document.querySelectorAll<HTMLElement>("[data-chat]");
    [...rows].find((row) => row.dataset.chat === last.id)?.focus();
  }, [chat]);

  const openChat = (id: string, event?: number) => {
    show(event === undefined ? { id } : { id, event });
  };

  // A pixie's page opens over the projects tab, where its row is.
  const openPixie = (id: string, pixieTab: PixieTab = "chat") => {
    setTab("projects");
    show({ pixie: id, tab: pixieTab });
  };

  return (
    <>
      <div
        className="view"
        id={`view-${tab}`}
        inert={chat !== null}
        role="tabpanel"
        aria-labelledby={`tab-${tab}`}
      >
        {tab === "inbox" && <Inbox onOpenChat={openChat} onOpenPixie={openPixie} />}
        {tab === "projects" && (
          <Projects
            project={current}
            onProject={setProject}
            onOpenChat={openChat}
            onOpenClaudeChat={(id) => {
              show({ claude: id });
            }}
            onNewChat={(repo) => {
              show({ draft: repo });
            }}
            onOpenPixie={openPixie}
          />
        )}
        {tab === "account" && <Account />}
      </div>
      {chat === null ? (
        <TabBar tab={tab} onTab={setTab} badge={needsCount(state)} />
      ) : (
        <ChatView
          // A different chat is a fresh view: no state of the last one is carried over.
          key={chatKey(chat)}
          target={chat}
          onBack={() => {
            closed.current = { id: chatId(chat) };
            setChat(null);
          }}
          onOpen={openChat}
          onOpenPixie={openPixie}
        />
      )}
    </>
  );
}

/** What an address opens over the tabs, if anything. */
function routeTarget({ chat, pixie }: Route): ChatTarget | null {
  if (pixie !== undefined) return { pixie };
  return chat === null ? null : { id: chat };
}

/** The row a target came from (its data-chat); null for a new chat. */
function chatId(target: ChatTarget): string | null {
  if ("claude" in target) return target.claude;
  if ("pixie" in target) return `pixie:${target.pixie}`;
  return "draft" in target ? null : target.id;
}

/** Which chat a target is, ignoring the event it opens at. */
function chatKey(target: ChatTarget): string {
  if ("claude" in target) return `claude:${target.claude}`;
  if ("pixie" in target) return `pixie:${target.pixie}`;
  return "draft" in target ? `new:${target.draft}` : `session:${target.id}`;
}
