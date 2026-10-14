import { useEffect, useState } from "react";
import type { Pixie, PixieActivity } from "../../api/types.ts";
import { activityTime } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import { Sheet } from "../../ui/Sheet.tsx";
import { toolWords } from "./options.ts";

interface Props {
  pixie: Pixie;
  onClose: () => void;
  onOpenChat: (sessionId: string) => void;
}

/** What the pixie did in chats (B41): time, tool, the chat and a summary, newest first. */
export function ActivityPage({ pixie, onClose, onOpenChat }: Props) {
  const { actions } = useStore();
  const { id } = pixie;
  // Undefined while loading, null when it could not load.
  const [log, setLog] = useState<PixieActivity[] | null | undefined>(undefined);

  useEffect(() => {
    void actions.pixieActivity(id).then(setLog);
  }, [actions, id]);

  return (
    <Sheet title="Activity" full onClose={onClose}>
      {log === undefined && <p className="hint">Loading...</p>}
      {log === null && <p className="hint">The activity could not be loaded.</p>}
      {log?.length === 0 && <p className="hint">Nothing yet</p>}
      {log !== null && log !== undefined && log.length > 0 && (
        <ul className="lgrp gl pxact">
          {log.map((entry) => (
            <Entry key={entry.id} entry={entry} onOpenChat={onOpenChat} />
          ))}
        </ul>
      )}
    </Sheet>
  );
}

function Entry({
  entry,
  onOpenChat,
}: {
  entry: PixieActivity;
  onOpenChat: (sessionId: string) => void;
}) {
  const { state } = useStore();
  const chatId = entry.session_id;
  const chat = chatId === null ? undefined : state.sessions[chatId];
  return (
    <li className="srow">
      <span className="pxdt">
        <span className="pxacth">
          <b>{toolWords(entry.tool)}</b>
          <small>{activityTime(entry.ts, new Date())}</small>
        </span>
        <span className="pxact-t">{entry.summary}</span>
        {chat !== undefined ? (
          <button
            className="pxlnk"
            onClick={() => {
              onOpenChat(chat.id);
            }}
          >
            {chat.title}
          </button>
        ) : (
          chatId !== null && <small>A chat no longer listed</small>
        )}
      </span>
    </li>
  );
}
