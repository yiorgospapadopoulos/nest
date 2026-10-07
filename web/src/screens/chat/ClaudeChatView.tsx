import { useEffect, useState } from "react";
import type { HarnessEvent } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { buildTranscript, type TranscriptItem } from "../../transcript/build.ts";
import { Pill } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { Frame } from "./Frame.tsx";
import { MessageItem, type MessageEntry } from "./Transcript.tsx";

interface Props {
  id: string;
  onBack: () => void;
  onOpen: (sessionId: string) => void;
}

const isMessage = (item: TranscriptItem): item is MessageEntry => item.kind !== "approval";

/** A Claude Code chat's history, read only, until the user continues it in harness. */
export function ClaudeChatView({ id, onBack, onOpen }: Props) {
  const { state, actions } = useStore();
  const chat = state.claudeChats[id];
  const [events, setEvents] = useState<HarnessEvent[] | null>(null);
  const [adopting, setAdopting] = useState(false);

  useEffect(() => {
    void actions.claudeChatEvents(id).then((loaded) => {
      setEvents(loaded ?? []);
    });
  }, [actions, id]);

  useEffect(() => {
    if (chat !== undefined) return;
    // Continued in harness (here or on another device), or gone from Claude Code.
    const adopted = Object.values(state.sessions).find((s) => s.provider_session_id === id);
    if (adopted === undefined) onBack();
    else onOpen(adopted.id);
  }, [chat, state.sessions, id, onBack, onOpen]);

  if (chat === undefined) return null;
  const items = buildTranscript(events ?? [], {}, chat.cwd).filter(isMessage);
  const open = chat.open_in_claude_code;

  const continueHere = async () => {
    setAdopting(true);
    // On success the chat leaves the list and the effect above opens the new session.
    if ((await actions.adoptClaudeChat(chat)) === null) setAdopting(false);
  };

  return (
    <Frame
      title={chat.title}
      back={chat.repo}
      onBack={onBack}
      details={
        <div className="ch-r2">
          <Pill
            tone={open ? "run" : "idle"}
            label={open ? "Open in Claude Code" : "Claude Code chat"}
          />
          {chat.worktree !== null && (
            <span className="chip">
              <Icon name="branch" />
              <span>{chat.worktree}</span>
            </span>
          )}
        </div>
      }
    >
      {/* Laid out from the end, so the newest messages show first without scrolling. */}
      <div className="ch-tx from-end">
        <div>
          {events === null && <p className="note">Loading...</p>}
          {events !== null && items.length === 0 && (
            <div className="tx-empty">
              <Icon name="spark" />
              <b>No messages yet</b>
            </div>
          )}
          <div className="tx">
            {items.map((item) => (
              <MessageItem key={item.key} item={item} />
            ))}
          </div>
        </div>
      </div>
      <div className="comp gl ccfoot">
        <p className="cnote">
          {open
            ? "Open in Claude Code right now. Close it there before sending from harness."
            : "Read only. Continue it here to send messages."}
        </p>
        <button className="b b-pri" disabled={adopting} onClick={() => void continueHere()}>
          Continue in harness
        </button>
      </div>
    </Frame>
  );
}
