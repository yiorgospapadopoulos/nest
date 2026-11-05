import { useEffect, useState } from "react";
import { useStore } from "../../store/context.ts";
import { buildTranscript } from "../../transcript/build.ts";

/** A Claude Code or Codex chat's history, read again when it moves on in its engine. */
export function useClaudeChat(id: string) {
  const { state, actions } = useStore();
  const chat = state.claudeChats[id];
  const [events, setEvents] = useState<Parameters<typeof buildTranscript>[0] | null>(null);
  useEffect(() => {
    void actions.claudeChatEvents(id).then((loaded) => {
      setEvents(loaded ?? []);
    });
  }, [actions, id, chat?.last_activity_at]);
  const items =
    chat === undefined
      ? []
      : buildTranscript(events ?? [], {}, chat.cwd).filter(
          (item) =>
            item.kind !== "approval" &&
            item.kind !== "pixie" &&
            item.kind !== "card" &&
            item.kind !== "artifact",
        );
  return { chat, loaded: events !== null, items };
}
