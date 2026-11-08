import { useCallback, useEffect, useRef, useState } from "react";
import { NAVIGATE, type NavigateMessage } from "../pwa/navigate.ts";
import { parseRoute, routePath, type Route, type SettingsPage, type Tab } from "../routes.ts";
import { useStore } from "../store/context.ts";
import { GENERAL_REPO, repoNamed } from "../store/general.ts";
import { needsCount } from "../store/selectors.ts";
import { ChatView, type ChatTarget } from "./chat/ChatView.tsx";
import type { PixieTab } from "./pixies/PixieView.tsx";
import { Inbox } from "./inbox/Inbox.tsx";
import type { WorkOf } from "./projects/ChatTree.tsx";
import { Projects } from "./projects/Projects.tsx";
import { Settings } from "./settings/Settings.tsx";
import { TabBar } from "./TabBar.tsx";
import { UpdateStrip } from "./UpdateStrip.tsx";

/** The three tabs, with a chat pushed full screen over them; the address follows along. */
export function Shell() {
  const { state } = useStore();
  const [initial] = useState(() => parseRoute(window.location.pathname));
  const [tab, setTab] = useState<Tab>(initial.tab);
  const [project, setProject] = useState<string | null>(null);
  // The Chats tab shows the pixies instead of a project (B102).
  const [pixies, setPixies] = useState(false);
  // The Settings page open.
  const [settings, setSettings] = useState<SettingsPage | null>(initial.settings ?? null);
  const [chat, setChat] = useState<ChatTarget | null>(() => routeTarget(initial));
  // The chosen project while it is still registered, else the first one, else General.
  const currentRepo =
    (project === null ? undefined : repoNamed(state.repos, project)) ??
    state.repos[0] ??
    GENERAL_REPO;
  const current = currentRepo.name;

  useEffect(() => {
    const path = routePath({
      tab,
      chat: chat !== null && "id" in chat ? chat.id : null,
      ...(chat !== null && "pixie" in chat ? { pixie: chat.pixie } : {}),
      ...(settings === null ? {} : { settings }),
    });
    if (window.location.pathname !== path) window.history.replaceState(null, "", path);
  }, [tab, chat, settings]);

  const closeSettings = useCallback(() => {
    setSettings(null);
  }, []);

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
      setSettings(route.settings ?? null);
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

  const openClaudeChat = (id: string) => {
    show({ claude: id });
  };

  const openWork = (workOf: string, who: WorkOf) => {
    show({ workOf, who });
  };

  // A pixie's page opens over the Chats tab's pixies, where its row is.
  const openPixie = (id: string, pixieTab: PixieTab = "chat") => {
    setTab("projects");
    setPixies(true);
    show({ pixie: id, tab: pixieTab });
  };

  return (
    // The page's one main landmark; it adds no box, as every part is placed on the app.
    <main>
      <div
        className={tab === "settings" ? "view" : "view flat"}
        id={`view-${tab}`}
        inert={chat !== null}
        role="tabpanel"
        aria-labelledby={`tab-${tab}`}
      >
        {tab === "inbox" && (
          <Inbox project={current} onOpenChat={openChat} onOpenPixie={openPixie} />
        )}
        {tab === "projects" && (
          <Projects
            repo={currentRepo}
            pixies={pixies}
            onProject={(name) => {
              setProject(name);
              setPixies(false);
            }}
            onPixies={() => {
              setPixies(true);
            }}
            onOpenChat={openChat}
            onOpenClaudeChat={openClaudeChat}
            onNewChat={(repo) => {
              show({ draft: repo });
            }}
            onOpenPixie={openPixie}
            onOpenAgent={(agentOf, call) => {
              show({ agentOf, call });
            }}
            onOpenWork={openWork}
            onUsage={() => {
              setTab("settings");
              setSettings({ page: "usage" });
            }}
          />
        )}
        {tab === "settings" && (
          <Settings
            page={settings}
            onPage={setSettings}
            back="Settings"
            onBack={closeSettings}
            onOpenPixie={openPixie}
          />
        )}
      </div>
      {/* A new chat keeps the tab bar, its composer docked above it; an open chat hides it. */}
      {(chat === null || "draft" in chat) && (
        <TabBar
          tab={tab}
          onTab={(next) => {
            // Settings opens on its list again, as a tab does when tapped.
            if (next === "settings" && tab === "settings") setSettings(null);
            // A tab leaves a new chat that was never sent; its draft stays.
            if (chat !== null) {
              opener.current = null;
              setChat(null);
            }
            setTab(next);
          }}
          badge={needsCount(state)}
        />
      )}
      {/* Over the tabs only: an open chat is full screen, a new chat's composer is here. */}
      {chat === null && <UpdateStrip />}
      {chat !== null && (
        <ChatView
          // A different chat is a fresh view: no state of the last one is carried over.
          key={chatKey(chat)}
          target={chat}
          onBack={() => {
            closed.current = { id: chatId(chat) };
            setChat(null);
          }}
          onOpen={openChat}
          onOpenClaudeChat={openClaudeChat}
          onOpenPixie={openPixie}
          onOpenWork={openWork}
        />
      )}
    </main>
  );
}

/** What an address opens over the tabs, if anything. */
function routeTarget({ chat, pixie }: Route): ChatTarget | null {
  if (pixie !== undefined) return { pixie };
  return chat === null ? null : { id: chat };
}

/** The row a target came from (its data-chat); null for a new chat. */
function chatId(target: ChatTarget): string | null {
  // A chat's subagent or pixie: back to the chat's row.
  if ("agentOf" in target) return target.agentOf;
  if ("workOf" in target) return target.workOf;
  if ("claude" in target) return target.claude;
  if ("pixie" in target) return `pixie:${target.pixie}`;
  return "draft" in target ? null : target.id;
}

/** Which chat a target is, ignoring the event it opens at. */
function chatKey(target: ChatTarget): string {
  if ("agentOf" in target) return `agent:${target.agentOf}:${target.call}`;
  if ("workOf" in target) return `work:${target.workOf}:${JSON.stringify(target.who)}`;
  if ("claude" in target) return `claude:${target.claude}`;
  if ("pixie" in target) return `pixie:${target.pixie}`;
  return "draft" in target ? `new:${target.draft}` : `session:${target.id}`;
}
