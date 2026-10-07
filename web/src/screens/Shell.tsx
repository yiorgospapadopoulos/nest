import { useEffect, useState } from "react";
import { NAVIGATE, type NavigateMessage } from "../pwa/navigate.ts";
import { parseRoute, routePath, type Route, type Tab } from "../routes.ts";
import { useStore } from "../store/context.ts";
import { needsCount } from "../store/selectors.ts";
import { Account } from "./account/Account.tsx";
import { ChatView, type ChatTarget } from "./chat/ChatView.tsx";
import { Inbox } from "./inbox/Inbox.tsx";
import { Projects } from "./projects/Projects.tsx";
import { TabBar } from "./TabBar.tsx";

/** The three tabs, with a chat pushed full screen over them; the address follows along. */
export function Shell() {
  const { state } = useStore();
  const [initial] = useState(() => parseRoute(window.location.pathname));
  const [tab, setTab] = useState<Tab>(initial.tab);
  const [project, setProject] = useState<string | null>(null);
  const [chat, setChat] = useState<ChatTarget | null>(
    initial.chat === null ? null : { id: initial.chat },
  );
  const current = project ?? state.repos[0]?.name ?? null;

  useEffect(() => {
    const path = routePath({ tab, chat: chat !== null && "id" in chat ? chat.id : null });
    if (window.location.pathname !== path) window.history.replaceState(null, "", path);
  }, [tab, chat]);

  // A tapped notification sends an open app to its item (see the service worker).
  useEffect(() => {
    const worker = window.navigator.serviceWorker as ServiceWorkerContainer | undefined;
    if (worker === undefined) return;
    const go = ({ tab: next, chat: id }: Route) => {
      setTab(next);
      setChat(id === null ? null : { id });
    };
    const onMessage = (event: MessageEvent<NavigateMessage | null>) => {
      if (event.data?.type === NAVIGATE) go(parseRoute(event.data.url));
    };
    worker.addEventListener("message", onMessage);
    return () => {
      worker.removeEventListener("message", onMessage);
    };
  }, []);

  const openChat = (id: string, event?: number) => {
    setChat(event === undefined ? { id } : { id, event });
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
        {tab === "inbox" && <Inbox onOpenChat={openChat} />}
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
            setChat(null);
          }}
          onOpen={openChat}
        />
      )}
    </>
  );
}

/** Which chat a target is, ignoring the event it opens at. */
function chatKey(target: ChatTarget): string {
  if ("claude" in target) return `claude:${target.claude}`;
  return "draft" in target ? `new:${target.draft}` : `session:${target.id}`;
}
