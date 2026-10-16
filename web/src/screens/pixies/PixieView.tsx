import { useEffect, useRef, useState } from "react";
import type { Pixie } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { pixieWorking } from "../../store/selectors.ts";
import { NO_BACKGROUND } from "../../store/state.ts";
import { Composer } from "../chat/Composer.tsx";
import { Frame } from "../chat/Frame.tsx";
import { Transcript } from "../chat/Transcript.tsx";
import { PixieDetails } from "./PixieDetails.tsx";
import { Sprite, WorkingDot } from "./Sprite.tsx";

export type PixieTab = "chat" | "details";

const TABS: readonly { tab: PixieTab; label: string }[] = [
  { tab: "chat", label: "Chat" },
  { tab: "details", label: "Details" },
];

interface Props {
  id: string;
  onBack: () => void;
  // Another pixie's page, from a call to it in the chat.
  onOpenPixie: (id: string) => void;
  // A chat it started or named, from a card or its activity log.
  onOpenChat: (sessionId: string) => void;
  tab?: PixieTab | undefined;
}

/** A pixie's page: its one ongoing chat, and the details that set it up (D072). */
export function PixieView({ id, onBack, onOpenPixie, onOpenChat, tab: first = "chat" }: Props) {
  const { state, actions } = useStore();
  const pixie = state.pixies[id];
  const [tab, setTab] = useState<PixieTab>(first);
  // Pixies load after the rest, so one not known yet may still come; one that goes is deleted.
  const seen = useRef(false);

  useEffect(() => {
    if (pixie !== undefined) seen.current = true;
    else if (seen.current) onBack();
  }, [pixie, onBack]);

  // For the Habits row, report cards and suggested habits (B42).
  useEffect(() => {
    void actions.loadHabits(id);
  }, [actions, id]);

  // Opening the pixie reads its reports, and so does one arriving while it is open.
  const unread = Object.values(state.reports)
    .filter((r) => r.pixie_id === id && r.read_at === null)
    .map((r) => r.id)
    .join(" ");
  const flagged = (pixie?.unread_action_reports ?? 0) > 0;
  useEffect(() => {
    if (unread !== "" || flagged) {
      void actions.readPixieReports(id, unread === "" ? [] : unread.split(" "));
    }
  }, [actions, id, unread, flagged]);

  if (pixie === undefined) {
    return (
      <Frame title="Pixie" back="Projects" onBack={onBack}>
        <div className="ch-tx" />
      </Frame>
    );
  }

  const working = pixieWorking(state, pixie);
  return (
    <Frame
      title={pixie.name}
      icon={
        <>
          <Sprite
            mascot={pixie.mascot}
            color={pixie.color}
            size={24}
            working={working}
            phaseKey={pixie.id}
          />
          <WorkingDot working={working} />
        </>
      }
      back="Projects"
      onBack={onBack}
      details={
        <div className="pxtabs mseg" role="tablist" aria-label={`${pixie.name} sections`}>
          {TABS.map(({ tab: value, label }) => (
            <button
              key={value}
              role="tab"
              id={`pixie-tab-${value}`}
              aria-selected={tab === value}
              aria-controls="pixie-panel"
              onClick={() => {
                setTab(value);
              }}
            >
              {label}
            </button>
          ))}
        </div>
      }
    >
      <div className={`pxbg pxbg-${pixie.background}`} aria-hidden="true" />
      {tab === "chat" ? (
        // A new chat (after the first message or a reset) is a fresh transcript.
        <PixieChat
          key={pixie.chat_session_id ?? "none"}
          pixie={pixie}
          working={working}
          onOpenPixie={onOpenPixie}
          onOpenChat={onOpenChat}
        />
      ) : (
        <div className="pxd" id="pixie-panel" role="tabpanel" aria-labelledby="pixie-tab-details">
          <PixieDetails pixie={pixie} working={working} onOpenChat={onOpenChat} />
        </div>
      )}
    </Frame>
  );
}

interface ChatProps {
  pixie: Pixie;
  working: boolean;
  onOpenPixie: (id: string) => void;
  onOpenChat: (sessionId: string) => void;
}

function PixieChat({ pixie, working, onOpenPixie, onOpenChat }: ChatProps) {
  const { state, actions } = useStore();
  const chatId = pixie.chat_session_id;
  const session = chatId === null ? undefined : state.sessions[chatId];

  useEffect(() => {
    if (chatId === null) return;
    void actions.openChat(chatId);
    return () => {
      actions.closeChat(chatId);
    };
  }, [actions, chatId]);

  return (
    <div className="pxchat" id="pixie-panel" role="tabpanel" aria-labelledby="pixie-tab-chat">
      {session === undefined ? (
        <div className="ch-tx">
          {chatId === null && (
            <div className="tx-empty pxhi">
              <Sprite
                mascot={pixie.mascot}
                color={pixie.color}
                size={96}
                working={working}
                phaseKey={pixie.id}
              />
              <b>Say hi to {pixie.name}</b>
              <span>It remembers what matters across chats.</span>
            </div>
          )}
        </div>
      ) : (
        <Transcript
          session={session}
          background={state.tracking[session.id]?.background ?? NO_BACKGROUND}
          history={state.history[session.id] ?? "loading"}
          onRetry={() => void actions.reloadChat(session.id)}
          onOpenPixie={onOpenPixie}
          onOpenChat={onOpenChat}
        />
      )}
      <Composer pixie={pixie.id} chat={session} />
    </div>
  );
}
