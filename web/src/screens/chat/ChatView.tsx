import { useEffect, useState } from "react";
import type { Pixie, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { chatStatus, exchangeBackground, pendingFor } from "../../store/selectors.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ChatActions } from "../projects/ChatActions.tsx";
import { NO_BACKGROUND } from "../../store/state.ts";
import { AgentsSheet } from "./AgentsSheet.tsx";
import { BackgroundBar } from "./BackgroundBar.tsx";
import { ClaudeChatView } from "./ClaudeChatView.tsx";
import type { ChatNav } from "./CommandSheets.tsx";
import { Composer } from "./Composer.tsx";
import { Frame } from "./Frame.tsx";
import { GoalsStrip } from "./GoalsStrip.tsx";
import { NewChat } from "./NewChat.tsx";
import { sessionPlace } from "./place.ts";
import { PlaceChip } from "./PlaceMarks.tsx";
import { PrChip } from "./PrChip.tsx";
import { ReviewBar } from "./ReviewBar.tsx";
import { Transcript } from "./Transcript.tsx";
import { useStopTask } from "./useStopTask.ts";
import { PixieView, type PixieTab } from "../pixies/PixieView.tsx";
import { StartedBy } from "../pixies/StartedBy.tsx";

// An open chat (optionally at an event, such as a search hit), a new one in a project that
// starts with its first message, or a Claude Code chat shown read only until it is
// continued in Nest, or a pixie's page (D072).
export type ChatTarget =
  | { id: string; event?: number }
  | { draft: string }
  | { claude: string }
  | { pixie: string; tab?: PixieTab };

interface Props {
  target: ChatTarget;
  onBack: () => void;
  onOpen: (sessionId: string, event?: number) => void;
  onOpenClaudeChat: (chatId: string) => void;
  onOpenPixie: (id: string) => void;
}

export function ChatView({ target, onBack, onOpen, onOpenClaudeChat, onOpenPixie }: Props) {
  const { state } = useStore();
  // A pixie's chat shows on its page, also when opened by its address or an inbox card.
  // A habit run's chat has the pixie too, but shows on its own, read only (B42).
  const opened = "id" in target ? state.sessions[target.id] : undefined;
  const pixieOfChat = opened?.habit_run_id == null ? opened?.pixie_id : undefined;
  useEffect(() => {
    if (pixieOfChat != null) onOpenPixie(pixieOfChat);
  }, [pixieOfChat, onOpenPixie]);
  const nav: ChatNav = {
    openChat: onOpen,
    openClaudeChat: onOpenClaudeChat,
    openPixie: onOpenPixie,
  };
  if ("claude" in target) {
    return <ClaudeChatView id={target.claude} onBack={onBack} onOpen={onOpen} />;
  }
  if ("pixie" in target) {
    return (
      <PixieView
        id={target.pixie}
        tab={target.tab}
        onBack={onBack}
        onOpenPixie={onOpenPixie}
        onOpenChat={onOpen}
      />
    );
  }
  return "draft" in target ? (
    <NewChat
      repo={target.draft}
      onBack={onBack}
      onCreated={(session) => {
        onOpen(session.id);
      }}
      nav={nav}
    />
  ) : (
    <SessionChat
      id={target.id}
      focus={target.event ?? null}
      onBack={onBack}
      onOpenPixie={onOpenPixie}
      onOpenChat={onOpen}
      nav={nav}
    />
  );
}

function SessionChat({
  id,
  focus,
  onBack,
  onOpenPixie,
  onOpenChat,
  nav,
}: {
  id: string;
  focus: number | null;
  onBack: () => void;
  onOpenPixie: (id: string) => void;
  onOpenChat: (sessionId: string) => void;
  nav: ChatNav;
}) {
  const { state, actions } = useStore();
  const session = state.sessions[id];
  const [sheet, setSheet] = useState<"agents" | "actions" | null>(null);
  const history = state.history[id];
  const stopper = useStopTask(id);
  // Whether the first fetch is over: the history itself goes when the chat is deleted.
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    void actions.openChat(id).then(() => {
      setLoaded(true);
    });
    return () => {
      actions.closeChat(id);
    };
  }, [actions, id]);

  useEffect(() => {
    // Deleted, here or on another device. A pixie chat is not in the session list, so
    // one opened by its address is known only once fetched.
    if (session === undefined && loaded) onBack();
  }, [session, loaded, onBack]);

  if (session === undefined) return null;
  const tracking = state.tracking[id] ?? { tasks: [], agents: [], background: NO_BACKGROUND };
  const active = tracking.agents.filter((a) => a.status === "running").length;
  const status = chatStatus(session, pendingFor(state, id));

  return (
    <Frame
      title={session.title}
      status={status}
      back={session.habit_run_id == null ? session.repo : runBack(state.pixies, session)}
      onBack={onBack}
      tools={
        <>
          <button
            className="ib"
            aria-haspopup="dialog"
            aria-label={`Agents, ${String(active)} active`}
            onClick={() => {
              setSheet("agents");
            }}
          >
            <Icon name="bot" />
            {active > 0 && <span className="cnt">{active}</span>}
          </button>
          <button
            className="ib"
            aria-haspopup="dialog"
            aria-label="Chat actions"
            onClick={() => {
              setSheet("actions");
            }}
          >
            <Icon name="dots" />
          </button>
        </>
      }
      details={<Details session={session} />}
    >
      <GoalsStrip tasks={tracking.tasks} />
      <Transcript
        session={session}
        background={tracking.background}
        focus={focus}
        history={history ?? "loading"}
        onRetry={() => void actions.reloadChat(id)}
        onOpenPixie={onOpenPixie}
        onOpenChat={onOpenChat}
      />
      {/* Until the history is in, the latest exchange and so its tasks are unknown. */}
      {history === "loaded" && (
        <BackgroundBar
          summary={exchangeBackground(tracking.background, state.transcripts[id])}
          stopper={stopper}
        />
      )}
      {session.habit_run_id == null ? (
        <>
          <ReviewBar session={session} />
          <Composer session={session} nav={nav} />
        </>
      ) : (
        <p className="note pxrun">A habit run. Its chat is read only.</p>
      )}
      {sheet === "agents" && (
        <AgentsSheet
          agents={tracking.agents}
          onClose={() => {
            setSheet(null);
          }}
        />
      )}
      {sheet === "actions" && (
        <ChatActions
          session={session}
          onClose={() => {
            setSheet(null);
          }}
          onGone={onBack}
        />
      )}
    </Frame>
  );
}

/** A habit run's chat goes back to its pixie's name rather than its "pixie:" repo. */
function runBack(pixies: Record<string, Pixie>, session: Session): string {
  return Object.values(pixies).find((p) => p.id === session.pixie_id)?.name ?? "Pixie";
}

function Details({ session }: { session: Session }) {
  const { state } = useStore();
  const place = sessionPlace(
    session,
    state.repos.find((r) => r.name === session.repo),
  );
  return (
    <div className="ch-r2">
      <PlaceChip place={place} />
      <PrChip session={session} />
      {session.started_by_pixie !== null && (
        <StartedBy id={session.started_by_pixie} className="chip" />
      )}
    </div>
  );
}
