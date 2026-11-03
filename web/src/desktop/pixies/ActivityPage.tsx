import { useEffect, useState } from "react";
import type { Pixie, PixieActivity } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { useShell } from "../shell/context.ts";
import { useNow } from "./useNow.ts";
import { clockTime } from "./habitText.ts";
import type { PixiePage } from "./panel.ts";
import { DetailLine, DetailNote, Page, PanelPageHeader } from "./parts.tsx";
import { ACTIVITY_EMPTY, toolWords } from "./words.ts";

/**
 * What the pixie did in Nest with its tools, newest first (B41): time, tool, the chat it
 * acted on (a click opens it) and a short summary. Read again after each of its turns.
 */
export function ActivityPage({ pixie, open }: { pixie: Pixie; open: (page: PixiePage) => void }) {
  const { state, actions } = useStore();
  // Undefined while it loads; null when it could not be read.
  const [entries, setEntries] = useState<PixieActivity[] | null | undefined>(undefined);
  const chat = pixie.chat_session_id === null ? undefined : state.sessions[pixie.chat_session_id];
  // The pixie's chat runs a turn; its end may have added entries.
  const working = chat?.state === "starting" || chat?.state === "running";

  useEffect(() => {
    let current = true;
    void actions.pixieActivity(pixie.id).then((loaded) => {
      if (current) setEntries(loaded);
    });
    return () => {
      current = false;
    };
  }, [actions, pixie.id, working]);

  return (
    <Page
      header={
        <PanelPageHeader
          title="Activity"
          back="Details"
          onBack={() => {
            open({ page: "details" });
          }}
        />
      }
    >
      {entries === null && <DetailLine text="Could not read the activity" dim />}
      {entries?.length === 0 && <DetailNote text={ACTIVITY_EMPTY} />}
      {entries?.map((entry) => (
        <ActivityRow key={entry.id} entry={entry} />
      ))}
    </Page>
  );
}

function ActivityRow({ entry }: { entry: PixieActivity }) {
  const { state } = useStore();
  const shell = useShell();
  const now = useNow();
  const session = entry.session_id === null ? undefined : state.sessions[entry.session_id];
  return (
    <div className="pd-activity">
      <div className="pd-activity-h">
        <span className="pd-activity-tool">{toolWords(entry.tool)}</span>
        {session !== undefined ? (
          <button
            className="pd-link"
            title={`Open ${session.title}`}
            onClick={() => {
              shell.openChat(session.id);
            }}
          >
            {session.title}
          </button>
        ) : (
          entry.session_id !== null && <span className="pd-activity-gone">A removed chat</span>
        )}
        <span className="pd-time">{clockTime(entry.ts, now)}</span>
      </div>
      {entry.summary !== "" && <p className="pd-activity-s pd-select">{entry.summary}</p>}
    </div>
  );
}
