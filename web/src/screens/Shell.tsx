import { useCallback, useEffect, useRef, useState } from "react";
import { NAVIGATE, type NavigateMessage } from "../pwa/navigate.ts";
import { parseRoute, routePath, type Route, type SettingsPage, type Tab } from "../routes.ts";
import { useStore } from "../store/context.ts";
import { needsCount } from "../store/selectors.ts";
import { ChatView, type ChatTarget } from "./chat/ChatView.tsx";
import type { PixieTab } from "./pixies/PixieView.tsx";
import { Inbox } from "./inbox/Inbox.tsx";
import type { WorkOf } from "./projects/ChatTree.tsx";
import { Projects } from "./projects/Projects.tsx";
import { Settings } from "./settings/Settings.tsx";
import { TabBar } from "./TabBar.tsx";

/** The three tabs, with a chat pushed full screen over them; the address follows along. */
export function Shell() {
  const { state } = useStore();
  const [initial] = useState(() => parseRoute(window.location.pathname));
  const [tab, setTab] = useState<Tab>(initial.tab);
  const [project, setProject] = useState<string | null>(null);
  // The Settings page open, and whether it was opened from the Projects tab (its gear),
  // where its back button returns.
  const [settings, setSettings] = useState<SettingsPage | null>(initial.settings ?? null);
  const [fromProjects, setFromProjects] = useState(false);
  const [chat, setChat] = useState<ChatTarget | null>(() => routeTarget(initial));
  // The chosen project while it is still registered, else the first one.
  const current = state.repos.find((r) => r.name === project)?.name ?? state.repos[0]?.name ?? null;

  useEffect(() => {
    const path = routePath({
      tab,
      chat: chat !== null && "id" in chat ? chat.id : null,
      ...(chat !== null && "pixie" in chat ? { pixie: chat.pixie } : {}),
      ...(settings === null ? {} : { settings }),
    });
    if (window.location.pathname !== path) window.history.replaceState(null, "", path);
  }, [tab, chat, settings]);

  const openSettings = useCallback((page: SettingsPage | null) => {
    setFromProjects(false);
    setSettings(page);
  }, []);
  const closeSettings = useCallback(() => {
    if (fromProjects) setTab("projects");
    setFromProjects(false);
    setSettings(null);
  }, [fromProjects]);

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
      setFromProjects(false);
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
            onOpenClaudeChat={openClaudeChat}
            onNewChat={(repo) => {
              show({ draft: repo });
            }}
            onOpenPixie={openPixie}
            onOpenAgent={(agentOf, call) => {
              show({ agentOf, call });
            }}
            onOpenWork={openWork}
            onOpenSettings={(name) => {
              setTab("settings");
              setSettings({ project: name });
              setFromProjects(true);
            }}
          />
        )}
        {tab === "settings" && (
          <Settings
            page={settings}
            onPage={openSettings}
            back={fromProjects ? "Projects" : "Settings"}
            onBack={closeSettings}
            onOpenPixie={openPixie}
          />
        )}
      </div>
      {chat === null ? (
        <TabBar
          tab={tab}
          onTab={(next) => {
            // Settings opens on its list again, as a tab does when tapped.
            if (next === "settings" && tab === "settings") openSettings(null);
            if (fromProjects) openSettings(null);
            setTab(next);
          }}
          badge={needsCount(state)}
        />
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
          onOpenClaudeChat={openClaudeChat}
          onOpenPixie={openPixie}
          onOpenWork={openWork}
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
