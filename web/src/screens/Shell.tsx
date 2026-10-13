import { useEffect, useRef, useState } from "react";
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

  // A tapped notification sends an open app to its item (see the service worker).
  useEffect(() => {
    const worker = window.navigator.serviceWorker as ServiceWorkerContainer | undefined;
    if (worker === undefined) return;
    const go = (route: Route) => {
      setTab(route.tab);
      setChat(routeTarget(route));
    };
    const onMessage = (event: MessageEvent<NavigateMessage | null>) => {
      if (event.data?.type === NAVIGATE) go(parseRoute(event.data.url));
    };
    worker.addEventListener("message", onMessage);
    return () => {
      worker.removeEventListener("message", onMessage);
    };
  }, []);

  // The chat that just closed: its row (data-chat) gets focus back once the tabs show again.
  const closed = useRef<string | null>(null);
  useEffect(() => {
    const id = closed.current;
    if (chat !== null || id === null) return;
    closed.current = null;
    const rows = document.querySelectorAll<HTMLElement>("[data-chat]");
    [...rows].find((row) => row.dataset.chat === id)?.focus();
  }, [chat]);

  const openChat = (id: string, event?: number) => {
    setChat(event === undefined ? { id } : { id, event });
  };

  // A pixie's page opens over the projects tab, where its row is.
  const openPixie = (id: string, pixieTab: PixieTab = "chat") => {
    setTab("projects");
    setChat({ pixie: id, tab: pixieTab });
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
              setChat({ claude: id });
            }}
            onNewChat={(repo) => {
              setChat({ draft: repo });
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
            closed.current = chatId(chat);
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
