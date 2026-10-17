import { useEffect, useState } from "react";
import type { NestEvent } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { buildTranscript, type TranscriptItem } from "../../transcript/build.ts";
import { Icon } from "../../ui/Icon.tsx";
import { Frame } from "./Frame.tsx";
import { claudeChatPlace } from "./place.ts";
import { PlaceChip } from "./PlaceMarks.tsx";
import { MessageItem, type MessageEntry } from "./Transcript.tsx";

interface Props {
  id: string;
  onBack: () => void;
  onOpen: (sessionId: string) => void;
}

const isMessage = (item: TranscriptItem): item is MessageEntry =>
  item.kind !== "approval" &&
  item.kind !== "pixie" &&
  item.kind !== "card" &&
  item.kind !== "artifact";

/** A Claude Code chat's history, read only, until the user continues it in Nest. */
export function ClaudeChatView({ id, onBack, onOpen }: Props) {
  const { state, actions } = useStore();
  const chat = state.claudeChats[id];
  const [events, setEvents] = useState<NestEvent[] | null>(null);
  const [adopting, setAdopting] = useState(false);

  useEffect(() => {
    void actions.claudeChatEvents(id).then((loaded) => {
      setEvents(loaded ?? []);
    });
  }, [actions, id]);

  useEffect(() => {
    if (chat !== undefined) return;
    // Continued in Nest (here or on another device), or gone from Claude Code.
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
      status={
        open
          ? { tone: "run", label: "Open in Claude Code", plain: true }
          : { tone: "idle", label: "Claude Code chat" }
      }
      back={chat.repo}
      onBack={onBack}
      details={
        <div className="ch-r2">
          <PlaceChip
            place={claudeChatPlace(
              chat,
              state.repos.find((r) => r.name === chat.repo),
            )}
          />
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
            ? "Open in Claude Code right now. Close it there before sending from Nest."
            : "Read only. Continue it here to send messages."}
        </p>
        <button className="b b-pri" disabled={adopting} onClick={() => void continueHere()}>
          Continue in Nest
        </button>
      </div>
    </Frame>
  );
}
