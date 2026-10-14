import { useEffect, useRef, useState } from "react";
import type { Pixie } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { NO_BACKGROUND } from "../../store/state.ts";
import { Composer } from "../chat/Composer.tsx";
import { Frame } from "../chat/Frame.tsx";
import { Transcript } from "../chat/Transcript.tsx";
import { PixieDetails } from "./PixieDetails.tsx";
import { Sprite } from "./Sprite.tsx";

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
  tab?: PixieTab | undefined;
}

/** A pixie's page: its one ongoing chat, and the details that set it up (D072). */
export function PixieView({ id, onBack, onOpenPixie, tab: first = "chat" }: Props) {
  const { state } = useStore();
  const pixie = state.pixies[id];
  const [tab, setTab] = useState<PixieTab>(first);
  // Pixies load after the rest, so one not known yet may still come; one that goes is deleted.
  const seen = useRef(false);

  useEffect(() => {
    if (pixie !== undefined) seen.current = true;
    else if (seen.current) onBack();
  }, [pixie, onBack]);

  if (pixie === undefined) {
    return (
      <Frame title="Pixie" back="Projects" onBack={onBack}>
        <div className="ch-tx" />
      </Frame>
    );
  }

  return (
    <Frame
      title={pixie.name}
      icon={<Sprite mascot={pixie.mascot} color={pixie.color} size={24} />}
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
        <PixieChat key={pixie.chat_session_id ?? "none"} pixie={pixie} onOpenPixie={onOpenPixie} />
      ) : (
        <div className="pxd" id="pixie-panel" role="tabpanel" aria-labelledby="pixie-tab-details">
          <PixieDetails pixie={pixie} />
        </div>
      )}
    </Frame>
  );
}

function PixieChat({ pixie, onOpenPixie }: { pixie: Pixie; onOpenPixie: (id: string) => void }) {
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
              <Sprite mascot={pixie.mascot} color={pixie.color} size={96} />
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
        />
      )}
      <Composer pixie={pixie.id} chat={session} />
    </div>
  );
}
