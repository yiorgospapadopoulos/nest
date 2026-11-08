// One chat's transcript and nothing else, a pane of the Mac app (B124): the same list and
// store as the window's ChatPane. The header, composer and bars around it stay native, so
// everything those own goes to the app through the bridge.
import { useEffect, useMemo, useRef, useState } from "react";
import type { Appearance } from "../../appearance/choices.ts";
import { useAppearance } from "../../appearance/context.ts";
import { workRoot } from "../../screens/approvals/hooks.ts";
import { useStore } from "../../store/context.ts";
import { NO_BACKGROUND, type BashRun } from "../../store/state.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import type { PanePost } from "../bridge.ts";
import { useBridge } from "../context.ts";
import { FileLinks } from "./FileLinks.tsx";
import { PANE_EVENT } from "./paneEvent.ts";
import { RowsContext, useRows, type ChatRows, type RowsHost } from "./rowsContext.ts";
import { ReadOnlyRows, Transcript, type TranscriptNav } from "./Transcript.tsx";
import type { TranscriptTarget, WorkTarget } from "./transcriptTarget.ts";
import { useClaudeChat } from "./useClaudeChat.ts";
import { PixieWork, SubagentWork } from "./WorkViews.tsx";

/** What the app tells the page, as `nest-pane` events (WebPaneBridge.swift). */
export type PaneCommand =
  | { kind: "dimmed"; value: boolean }
  | { kind: "focus"; event: number }
  | ({ kind: "appearance" } & Pick<Appearance, "theme" | "accent">)
  | { kind: "bash"; runs: BashRun[] };

// As long as a hit glows; after it the same event can be asked for again.
const HIT_MS = 2000;

const noPost: PanePost = () => Promise.resolve();
// What Page Up leaves in view of the page before it, as a native scroll view does.
const PAGE_OVERLAP = 40;

/**
 * The keys that scroll the transcript. WebKit's own animated keyboard scrolling stops at
 * the first scroll position the list sets, which a list that measures rows does at once.
 */
function scrollKey(event: KeyboardEvent): void {
  const el = document.querySelector<HTMLElement>(".dc-tx");
  const target = event.target as Partial<HTMLElement> | null;
  const typing =
    target?.isContentEditable === true || /^(INPUT|TEXTAREA)$/.test(target?.tagName ?? "");
  if (el === null || typing || event.metaKey || event.ctrlKey || event.altKey) return;
  const page = el.clientHeight - PAGE_OVERLAP;
  const to: Record<string, number> = {
    PageUp: el.scrollTop - page,
    PageDown: el.scrollTop + page,
    Home: 0,
    End: el.scrollHeight,
  };
  const top = to[event.key];
  if (top === undefined) return;
  event.preventDefault();
  el.scrollTop = top;
}

function useHost(post: PanePost): RowsHost {
  return useMemo(
    () => ({
      messageAction: (action, event) => void post({ kind: "message", action, event }),
      openArtifact: (id, version) => void post({ kind: "artifact", id, version }),
      runInTerminal: (command) => void post({ kind: "terminal", command }),
      openImage: (id) => void post({ kind: "image", id }),
    }),
    [post],
  );
}

export function TranscriptPage({ target }: { target: TranscriptTarget }) {
  const { state, actions } = useStore();
  const { change } = useAppearance();
  const changeAppearance = useRef(change);
  const post = useBridge().pane ?? noPost;
  const [dimmed, setDimmed] = useState(false);
  const [focus, setFocus] = useState<number | null>(null);
  const [bash, setBash] = useState<BashRun[]>([]);

  useEffect(() => {
    changeAppearance.current = change;
  }, [change]);

  // Past its first load: the app gives a page that never gets here a way out.
  const ready = state.auth === "ready";
  useEffect(() => {
    if (ready) void post({ kind: "ready" });
  }, [ready, post]);

  useEffect(() => {
    const receive = (event: Event) => {
      const command = (event as CustomEvent<PaneCommand>).detail;
      switch (command.kind) {
        case "dimmed":
          setDimmed(command.value);
          break;
        case "focus":
          setFocus(command.event);
          break;
        case "appearance":
          changeAppearance.current({ theme: command.theme, accent: command.accent });
          break;
        case "bash":
          setBash(command.runs);
          break;
      }
    };
    window.addEventListener(PANE_EVENT, receive);
    return () => {
      window.removeEventListener(PANE_EVENT, receive);
    };
  }, [post]);

  useEffect(() => {
    window.addEventListener("keydown", scrollKey);
    return () => {
      window.removeEventListener("keydown", scrollKey);
    };
  }, []);

  useEffect(() => {
    if (focus === null) return;
    const timer = window.setTimeout(() => {
      setFocus(null);
    }, HIT_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [focus]);

  // The app shows notes in its own place, once for the window.
  const { toast } = state;
  useEffect(() => {
    if (toast === null) return;
    void post({ kind: "toast", text: toast.text, tone: toast.tone });
    actions.dismissToast();
  }, [toast, post, actions]);

  if (!ready) return <Waiting />;
  if ("chat" in target) {
    return (
      <ChatTranscript chat={target.chat} dimmed={dimmed} focus={focus} bash={bash} post={post} />
    );
  }
  if ("claude" in target) return <ClaudeTranscript id={target.claude} post={post} />;
  return <WorkTranscript target={target.work} post={post} />;
}

function Waiting() {
  return (
    <div className="dc-page">
      <div className="dc-loading">
        <Fireflies size={12} />
      </div>
    </div>
  );
}

function ChatTranscript({
  chat,
  dimmed,
  focus,
  bash,
  post,
}: {
  chat: string;
  dimmed: boolean;
  focus: number | null;
  bash: BashRun[];
  post: PanePost;
}) {
  const { state, actions } = useStore();
  const session = state.sessions[chat];
  const host = useHost(post);
  useEffect(() => {
    void actions.openChat(chat);
    return () => {
      actions.closeChat(chat);
    };
  }, [actions, chat]);
  const project = session?.pixie_id == null;
  const nav = useMemo<TranscriptNav>(
    () => ({
      openPixie: (pixie) => void post({ kind: "open", target: { pixie } }),
      openTeamWork: project ? (team) => void post({ kind: "teamWork", team }) : null,
      openPixieWork: project ? (pixie) => void post({ kind: "pixieWork", pixie }) : null,
      openChat: (id) => void post({ kind: "open", target: { chat: id } }),
      host,
    }),
    [post, project, host],
  );
  if (session === undefined) return <Waiting />;
  return (
    <FileLinks folder={workRoot(session)} session={session.id}>
      <div className="dc-page">
        <Transcript
          session={session}
          background={state.tracking[chat]?.background ?? NO_BACKGROUND}
          focus={focus}
          history={state.history[chat] ?? "loading"}
          onRetry={() => void actions.reloadChat(chat)}
          dimmed={dimmed}
          nav={nav}
          bash={bash}
        />
      </div>
    </FileLinks>
  );
}

function ClaudeTranscript({ id, post }: { id: string; post: PanePost }) {
  const { chat, loaded, items } = useClaudeChat(id);
  const host = useHost(post);
  return (
    <FileLinks folder={chat?.cwd ?? null}>
      <div className="dc-page">
        <div className="dc-txw">
          <div className="dc-tx from-end">
            <div className="dc-txin">
              {!loaded && (
                <p className="dc-empty">
                  <Fireflies size={11} />
                </p>
              )}
              <ReadOnlyRows chat={`claude:${id}`} items={items} host={host} />
              {loaded && items.length === 0 && <p className="dc-empty">No messages yet</p>}
            </div>
          </div>
        </div>
      </div>
    </FileLinks>
  );
}

/** A chat's work, read-only, for the app's work sheet: its chat stays open behind it. */
function WorkTranscript({ target, post }: { target: WorkTarget; post: PanePost }) {
  const { state, actions } = useStore();
  const { session } = target;
  const host = useHost(post);
  const outer = useRows();
  useEffect(() => {
    void actions.openChat(session);
    return () => {
      actions.closeChat(session);
    };
  }, [actions, session]);
  const openChat = (id: string) => void post({ kind: "open", target: { chat: id } });
  const rows: ChatRows = {
    ...outer,
    chat: session,
    session: state.sessions[session],
    openPixie: (pixie) => void post({ kind: "open", target: { pixie } }),
    openChat,
    host,
  };
  return (
    <FileLinks folder={workRoot(state.sessions[session])} session={session}>
      <RowsContext value={rows}>
        <div className="dc-page">
          <div className="dc-tx">
            <div className="dc-txin">
              {"call" in target ? (
                <SubagentWork session={session} call={target.call} onOpenChat={openChat} />
              ) : (
                <PixieWork
                  session={session}
                  who={"pixie" in target ? { pixie: target.pixie } : { team: target.team }}
                  onOpenChat={openChat}
                />
              )}
            </div>
          </div>
        </div>
      </RowsContext>
    </FileLinks>
  );
}
