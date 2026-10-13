import { useEffect, useState } from "react";
import type { Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { chatStatus, exchangeBackground, pendingFor } from "../../store/selectors.ts";
import { Pill } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { ChatActions } from "../projects/ChatActions.tsx";
import { NO_BACKGROUND } from "../../store/state.ts";
import { AgentsSheet } from "./AgentsSheet.tsx";
import { BackgroundBar } from "./BackgroundBar.tsx";
import { ClaudeChatView } from "./ClaudeChatView.tsx";
import { Composer } from "./Composer.tsx";
import { Frame } from "./Frame.tsx";
import { GoalsStrip } from "./GoalsStrip.tsx";
import { PrChip } from "./PrChip.tsx";
import { Transcript } from "./Transcript.tsx";

// An open chat (optionally at an event, such as a search hit), a new one in a project that
// starts with its first message, or a Claude Code chat shown read only until it is
// continued in harness.
export type ChatTarget = { id: string; event?: number } | { draft: string } | { claude: string };

interface Props {
  target: ChatTarget;
  onBack: () => void;
  onOpen: (sessionId: string) => void;
}

export function ChatView({ target, onBack, onOpen }: Props) {
  if ("claude" in target) {
    return <ClaudeChatView id={target.claude} onBack={onBack} onOpen={onOpen} />;
  }
  return "draft" in target ? (
    <Frame title="New chat" back={target.draft} onBack={onBack}>
      <div className="ch-tx">
        <div className="tx-empty">
          <Icon name="spark" />
          <b>New chat</b>
          <span>Describe the task. The agent starts when you send it.</span>
        </div>
      </div>
      <Composer
        repo={target.draft}
        onCreated={(session) => {
          onOpen(session.id);
        }}
      />
    </Frame>
  ) : (
    <SessionChat id={target.id} focus={target.event ?? null} onBack={onBack} />
  );
}

function SessionChat({
  id,
  focus,
  onBack,
}: {
  id: string;
  focus: number | null;
  onBack: () => void;
}) {
  const { state, actions } = useStore();
  const session = state.sessions[id];
  const [sheet, setSheet] = useState<"agents" | "actions" | null>(null);
  const history = state.history[id];

  useEffect(() => {
    void actions.openChat(id);
    return () => {
      actions.closeChat(id);
    };
  }, [actions, id]);

  useEffect(() => {
    // Deleted, here or on another device.
    if (session === undefined) onBack();
  }, [session, onBack]);

  if (session === undefined) return null;
  const tracking = state.tracking[id] ?? { tasks: [], agents: [], background: NO_BACKGROUND };
  const active = tracking.agents.filter((a) => a.status === "running").length;
  const status = chatStatus(session, pendingFor(state, id));

  return (
    <Frame
      title={session.title}
      back={session.repo}
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
      details={<Details session={session} label={status.label} tone={status.tone} />}
    >
      <GoalsStrip tasks={tracking.tasks} />
      <Transcript
        session={session}
        background={tracking.background}
        focus={focus}
        history={history ?? "loading"}
        onRetry={() => void actions.reloadChat(id)}
      />
      {/* Until the history is in, the latest exchange and so its tasks are unknown. */}
      {history === "loaded" && (
        <BackgroundBar summary={exchangeBackground(tracking.background, state.transcripts[id])} />
      )}
      <Composer session={session} />
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

function Details({ session, label, tone }: { session: Session } & Parameters<typeof Pill>[0]) {
  return (
    <div className="ch-r2">
      <Pill tone={tone} label={label} />
      {session.branch !== null && (
        <span className="chip">
          <Icon name="branch" />
          <span>{session.branch}</span>
        </span>
      )}
      <PrChip session={session} />
    </div>
  );
}
